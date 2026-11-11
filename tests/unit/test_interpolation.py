from collections.abc import Sequence

import polars as pl
import pytest

from app.domain.params import AnalysisParams
from app.domain.pipeline.interpolation import interpolate_rows, interpolate_values

_PARAMS = AnalysisParams()


def _make_df(**kwargs: Sequence[object]) -> pl.DataFrame:
    n = max(len(v) for v in kwargs.values())
    base: dict[str, list[object]] = {
        "vehicle_id": ["V1"] * n,
        "ts": list(range(1_700_000_000, 1_700_000_000 + n)),
        "speed": [60.0] * n,
        "lat": [37.5] * n,
        "lon": [127.0] * n,
        "trip_id": [1] * n,
        "speed_invalid": [False] * n,
        "speed_out_of_range": [False] * n,
        "gps_swapped": [False] * n,
        "gps_invalid": [False] * n,
        "speed_spike": [False] * n,
        "gps_teleport": [False] * n,
        "is_interpolated": [False] * n,
    }
    for k, v in kwargs.items():
        base[k] = list(v)
    return pl.DataFrame(base)


# --- interpolate_values ---


def test_interpolate_values_fills_null_speed() -> None:
    df = _make_df(speed=[60.0, None, 80.0])
    result = interpolate_values(df, _PARAMS)
    assert result["speed"][1] == pytest.approx(70.0)
    assert result["is_interpolated"][1] is True


def test_interpolate_values_fills_null_gps() -> None:
    df = _make_df(lat=[37.5, None, 37.7], lon=[127.0, None, 127.2])
    result = interpolate_values(df, _PARAMS)
    assert result["lat"][1] == pytest.approx(37.6)
    assert result["lon"][1] == pytest.approx(127.1)
    assert result["is_interpolated"][1] is True


def test_interpolate_values_does_not_fill_beyond_max_gap() -> None:
    max_gap = _PARAMS.interp_max_gap_sec
    ts = [1_700_000_000, 1_700_000_000 + max_gap + 1, 1_700_000_000 + max_gap + 2]
    df = _make_df(ts=ts, speed=[60.0, None, 80.0])
    result = interpolate_values(df, _PARAMS)
    assert result["speed"][1] is None
    assert result["is_interpolated"][1] is False


def test_interpolate_values_fills_consecutive_nulls() -> None:
    df = _make_df(
        ts=[1_700_000_000, 1_700_000_001, 1_700_000_002, 1_700_000_003],
        speed=[60.0, None, None, 90.0],
    )
    result = interpolate_values(df, _PARAMS)
    assert result["speed"][1] == pytest.approx(70.0)
    assert result["speed"][2] == pytest.approx(80.0)
    assert result["is_interpolated"][1] is True
    assert result["is_interpolated"][2] is True


def test_interpolate_values_does_not_fill_trip_boundary() -> None:
    df = _make_df(
        trip_id=[1, 2, 2],
        speed=[60.0, None, 80.0],
    )
    result = interpolate_values(df, _PARAMS)
    assert result["speed"][1] is None


# --- interpolate_rows ---


def test_interpolate_rows_fills_gap() -> None:
    df = _make_df(
        ts=[1_700_000_000, 1_700_000_003],
        speed=[60.0, 90.0],
        lat=[37.5, 37.8],
        lon=[127.0, 127.3],
    )
    result = interpolate_rows(df, _PARAMS)
    assert result.height == 4
    interp = result.filter(pl.col("is_interpolated"))
    assert interp.height == 2
    assert interp["speed"].to_list() == pytest.approx([70.0, 80.0])


def test_interpolate_rows_does_not_fill_gap_exceeding_max() -> None:
    max_gap = _PARAMS.interp_max_gap_sec
    df = _make_df(
        ts=[1_700_000_000, 1_700_000_000 + max_gap + 1],
        speed=[60.0, 90.0],
    )
    result = interpolate_rows(df, _PARAMS)
    assert result.height == 2


def test_interpolate_rows_does_not_cross_trip_boundary() -> None:
    df = _make_df(
        trip_id=[1, 2],
        ts=[1_700_000_000, 1_700_000_003],
        speed=[60.0, 90.0],
    )
    result = interpolate_rows(df, _PARAMS)
    assert result.height == 2
