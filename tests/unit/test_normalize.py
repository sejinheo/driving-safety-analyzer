import polars as pl
import pytest

from app.domain.params import AnalysisParams
from app.domain.pipeline.normalize import normalize

_PARAMS = AnalysisParams()


def _make_df(**kwargs: list[object]) -> pl.DataFrame:
    n = max(len(v) for v in kwargs.values())
    base: dict[str, list[object]] = {
        "vehicle_id": [None] * n,
        "ts_raw": [None] * n,
        "speed_raw": [None] * n,
        "lat_raw": [None] * n,
        "lon_raw": [None] * n,
    }
    for k, v in kwargs.items():
        base[k] = list(v)
    return pl.DataFrame(base)


def test_normalize_rejects_missing_timestamp() -> None:
    df = _make_df(ts_raw=[None, 1_700_000_000])
    clean, rejected = normalize(df, _PARAMS)
    assert rejected.filter(pl.col("reason") == "MISSING_TIMESTAMP").height == 1
    assert clean.height == 1


def test_normalize_rejects_invalid_timestamp() -> None:
    df = _make_df(ts_raw=["not-a-ts", "2023-11-14T22:13:20Z"])
    clean, rejected = normalize(df, _PARAMS)
    assert rejected.filter(pl.col("reason") == "INVALID_TIMESTAMP").height == 1
    assert clean.height == 1


def test_normalize_rejects_timestamp_out_of_range() -> None:
    df = _make_df(ts_raw=[100, 1_700_000_000, 9_999_999_999])
    clean, rejected = normalize(df, _PARAMS)
    assert rejected.filter(pl.col("reason") == "TIMESTAMP_OUT_OF_RANGE").height == 2
    assert clean.height == 1


def test_normalize_millisecond_timestamp_accepted() -> None:
    df = _make_df(ts_raw=[1_700_000_000_000])
    clean, _ = normalize(df, _PARAMS)
    assert clean.height == 1
    assert clean["ts"][0] == 1_700_000_000


@pytest.mark.parametrize(
    "speed_raw, expect_speed, expect_invalid, expect_out_of_range",
    [
        (60.0, 60.0, False, False),
        (0.0, 0.0, False, False),
        (250.0, 250.0, False, False),
        (-1.0, None, False, True),
        (300.0, None, False, True),
        ("fast", None, True, False),
        (None, None, False, False),
    ],
    ids=["normal", "zero", "max", "negative", "over_max", "invalid_string", "null"],
)
def test_normalize_speed_flags(
    speed_raw: object,
    expect_speed: float | None,
    expect_invalid: bool,
    expect_out_of_range: bool,
) -> None:
    df = _make_df(ts_raw=[1_700_000_000], speed_raw=[speed_raw])
    clean, _ = normalize(df, _PARAMS)
    assert clean.height == 1
    row = clean.row(0, named=True)
    if expect_speed is None:
        assert row["speed"] is None
    else:
        assert row["speed"] == pytest.approx(expect_speed)
    assert row["speed_invalid"] == expect_invalid
    assert row["speed_out_of_range"] == expect_out_of_range


def test_normalize_valid_gps() -> None:
    df = _make_df(ts_raw=[1_700_000_000], lat_raw=[37.5665], lon_raw=[126.9780])
    clean, _ = normalize(df, _PARAMS)
    row = clean.row(0, named=True)
    assert row["gps_swapped"] is False
    assert row["gps_invalid"] is False
    assert row["lat"] == pytest.approx(37.5665)
    assert row["lon"] == pytest.approx(126.9780)


def test_normalize_gps_swapped_detected_and_corrected() -> None:
    df = _make_df(ts_raw=[1_700_000_000], lat_raw=[126.9780], lon_raw=[37.5665])
    clean, _ = normalize(df, _PARAMS)
    row = clean.row(0, named=True)
    assert row["gps_swapped"] is True
    assert row["gps_invalid"] is False
    assert row["lat"] == pytest.approx(37.5665)
    assert row["lon"] == pytest.approx(126.9780)


def test_normalize_gps_out_of_range_nullified() -> None:
    df = _make_df(ts_raw=[1_700_000_000], lat_raw=[91.0], lon_raw=[181.0])
    clean, _ = normalize(df, _PARAMS)
    row = clean.row(0, named=True)
    assert row["gps_invalid"] is True
    assert row["lat"] is None
    assert row["lon"] is None


def test_normalize_gps_zero_coordinate_invalid() -> None:
    df = _make_df(ts_raw=[1_700_000_000], lat_raw=[0.0], lon_raw=[0.0])
    clean, _ = normalize(df, _PARAMS)
    row = clean.row(0, named=True)
    assert row["gps_invalid"] is True
    assert row["lat"] is None
    assert row["lon"] is None


def test_normalize_gps_null_input_invalid() -> None:
    df = _make_df(ts_raw=[1_700_000_000], lat_raw=[None], lon_raw=[None])
    clean, _ = normalize(df, _PARAMS)
    assert clean.row(0, named=True)["gps_invalid"] is True


def test_normalize_null_vehicle_id_becomes_unknown() -> None:
    df = _make_df(ts_raw=[1_700_000_000], vehicle_id=[None])
    clean, _ = normalize(df, _PARAMS)
    assert clean["vehicle_id"][0] == "UNKNOWN"


def test_normalize_integer_vehicle_id_cast_to_string() -> None:
    df = _make_df(ts_raw=[1_700_000_000], vehicle_id=[12345])
    clean, _ = normalize(df, _PARAMS)
    assert clean["vehicle_id"][0] == "12345"
