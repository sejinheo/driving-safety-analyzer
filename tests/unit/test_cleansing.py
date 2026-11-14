import polars as pl
import pytest

from app.domain.params import AnalysisParams
from app.domain.pipeline.cleansing import (
    merge_duplicates,
    remove_gps_teleports,
    remove_speed_spikes,
)

_PARAMS = AnalysisParams()


def _make_df(**kwargs: list[object]) -> pl.DataFrame:
    n = max(len(v) for v in kwargs.values())
    base: dict[str, list[object]] = {
        "vehicle_id": ["V1"] * n,
        "ts": list(range(1_700_000_000, 1_700_000_000 + n)),
        "source_index": list(range(n)),
        "speed": [60.0] * n,
        "lat": [37.5] * n,
        "lon": [127.0] * n,
        "trip_id": [1] * n,
        "speed_invalid": [False] * n,
        "speed_out_of_range": [False] * n,
        "gps_swapped": [False] * n,
        "gps_invalid": [False] * n,
    }
    for k, v in kwargs.items():
        base[k] = list(v)
    return pl.DataFrame(base)


# --- merge_duplicates ---


def test_merge_duplicates_removes_exact_duplicate() -> None:
    df = _make_df(
        vehicle_id=["V1", "V1"],
        ts=[1_700_000_000, 1_700_000_000],
        speed=[60.0, 80.0],
    )
    merged, count = merge_duplicates(df)
    assert merged.height == 1
    assert count == 1
    assert merged["speed"][0] == pytest.approx(70.0)


def test_merge_duplicates_averages_null_excluded() -> None:
    df = _make_df(
        vehicle_id=["V1", "V1"],
        ts=[1_700_000_000, 1_700_000_000],
        speed=[None, 80.0],
    )
    merged, _ = merge_duplicates(df)
    assert merged["speed"][0] == pytest.approx(80.0)


def test_merge_duplicates_all_null_speed_stays_null() -> None:
    df = _make_df(
        vehicle_id=["V1", "V1"],
        ts=[1_700_000_000, 1_700_000_000],
        speed=[None, None],
    )
    merged, _ = merge_duplicates(df)
    assert merged["speed"][0] is None


def test_merge_duplicates_flags_or() -> None:
    df = _make_df(
        vehicle_id=["V1", "V1"],
        ts=[1_700_000_000, 1_700_000_000],
        speed_invalid=[True, False],
        speed_out_of_range=[False, True],
    )
    merged, _ = merge_duplicates(df)
    assert merged["speed_invalid"][0] is True
    assert merged["speed_out_of_range"][0] is True


def test_merge_duplicates_no_duplicate_unchanged() -> None:
    df = _make_df(
        vehicle_id=["V1", "V1"],
        ts=[1_700_000_000, 1_700_000_001],
    )
    merged, count = merge_duplicates(df)
    assert merged.height == 2
    assert count == 0


# --- remove_speed_spikes ---


def test_remove_speed_spikes_detects_spike() -> None:
    # 60 → 200 → 60: 순간 튀었다가 돌아옴
    df = _make_df(speed=[60.0, 200.0, 60.0])
    result = remove_speed_spikes(df, _PARAMS)
    assert result["speed_spike"][1] is True
    assert result["speed"][1] is None


def test_remove_speed_spikes_sustained_change_not_spike() -> None:
    # 60 → 200 → 200: 급변 후 유지 → 노이즈 아님
    df = _make_df(speed=[60.0, 200.0, 200.0])
    result = remove_speed_spikes(df, _PARAMS)
    assert result["speed_spike"][1] is False
    assert result["speed"][1] == pytest.approx(200.0)


def test_remove_speed_spikes_requires_1sec_interval() -> None:
    # dt가 1초가 아니면 스파이크로 판정 안 함
    df = _make_df(
        ts=[1_700_000_000, 1_700_000_002, 1_700_000_004],
        speed=[60.0, 200.0, 60.0],
    )
    result = remove_speed_spikes(df, _PARAMS)
    assert result["speed_spike"][1] is False


def test_remove_speed_spikes_no_spike_when_null_neighbor() -> None:
    df = _make_df(speed=[None, 200.0, 60.0])
    result = remove_speed_spikes(df, _PARAMS)
    assert result["speed_spike"][1] is False


def test_remove_speed_spikes_does_not_cross_trip_boundary() -> None:
    # 같은 speed 패턴이지만 trip_id가 다르면 판정 안 함
    df = _make_df(
        trip_id=[1, 2, 2],
        speed=[60.0, 200.0, 60.0],
    )
    result = remove_speed_spikes(df, _PARAMS)
    assert result["speed_spike"][1] is False


# --- remove_gps_teleports ---


def test_remove_gps_teleports_detects_teleport() -> None:
    # 가운데 점이 갑자기 1도 이동(약 111km), dt=1초 → gps_speed >> sensor_speed
    df = _make_df(
        lat=[37.5, 38.5, 37.5],
        lon=[127.0, 127.0, 127.0],
        speed=[60.0, 60.0, 60.0],
    )
    result = remove_gps_teleports(df, _PARAMS)
    assert result["gps_teleport"][1] is True
    assert result["lat"][1] is None
    assert result["lon"][1] is None


def test_remove_gps_teleports_normal_movement_not_flagged() -> None:
    # 1초에 약 17m 이동(60km/h) → 순간이동 아님
    lat_base = 37.5
    delta = 60 / 3600 / 111_000  # 약 0.00015도
    df = _make_df(
        lat=[lat_base, lat_base + delta, lat_base + delta * 2],
        lon=[127.0, 127.0, 127.0],
        speed=[60.0, 60.0, 60.0],
    )
    result = remove_gps_teleports(df, _PARAMS)
    assert result["gps_teleport"].to_list() == [False, False, False]


def test_remove_gps_teleports_does_not_cross_trip_boundary() -> None:
    # trip 1의 마지막 점(37.5)과 trip 2의 첫 점(38.5) 사이의 큰 거리는
    # 서로 다른 trip이므로 순간이동 판정 대상이 아님
    # → trip 1의 마지막 점(index 0)이 이상 점으로 판정되면 안 됨
    df = _make_df(
        trip_id=[1, 2, 2],
        lat=[37.5, 38.5, 38.6],
        lon=[127.0, 127.0, 127.0],
        speed=[60.0, 60.0, 60.0],
    )
    result = remove_gps_teleports(df, _PARAMS)
    assert result["gps_teleport"][0] is False
