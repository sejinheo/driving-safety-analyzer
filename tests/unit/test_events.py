from collections.abc import Sequence

import polars as pl

from app.domain.enums import EventType
from app.domain.params import AnalysisParams
from app.domain.pipeline.events import detect_harsh_events, detect_school_zone_events

_PARAMS = AnalysisParams()
_BASE_TS = 1_700_000_000


def _make_df(**kwargs: Sequence[object]) -> pl.DataFrame:
    n = max(len(v) for v in kwargs.values())
    base: dict[str, list[object]] = {
        "vehicle_id": ["V1"] * n,
        "trip_id": [1] * n,
        "ts": list(range(_BASE_TS, _BASE_TS + n)),
        "speed": [50.0] * n,
        "lat": [37.5] * n,
        "lon": [127.0] * n,
        "is_interpolated": [False] * n,
    }
    for k, v in kwargs.items():
        base[k] = list(v)
    return pl.DataFrame(base)


def _zone_hits(trip_id: int, ts_list: list[int], zone_name: str = "A초등학교") -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trip_id": [trip_id] * len(ts_list),
            "ts": ts_list,
            "zone_name": [zone_name] * len(ts_list),
        }
    )


# --- harsh events ---


def test_harsh_accel_single_pair() -> None:
    df = _make_df(speed=[50.0, 61.0])
    result = detect_harsh_events(df, _PARAMS)
    assert result.height == 1
    assert result["type"][0] == EventType.HARSH_ACCEL
    assert result["start_ts"][0] == _BASE_TS
    assert result["end_ts"][0] == _BASE_TS + 1


def test_harsh_decel_type_assigned() -> None:
    df = _make_df(speed=[61.0, 50.0])
    result = detect_harsh_events(df, _PARAMS)
    assert result.height == 1
    assert result["type"][0] == EventType.HARSH_DECEL


def test_harsh_accel_consecutive_pairs_merged() -> None:
    df = _make_df(speed=[50.0, 61.0, 72.0])
    result = detect_harsh_events(df, _PARAMS)
    assert result.height == 1
    assert result["start_ts"][0] == _BASE_TS
    assert result["end_ts"][0] == _BASE_TS + 2


def test_harsh_events_split_by_dt_gap() -> None:
    ts = [_BASE_TS, _BASE_TS + 1, _BASE_TS + 3, _BASE_TS + 4]
    df = _make_df(ts=ts, speed=[50.0, 61.0, 50.0, 61.0])
    result = detect_harsh_events(df, _PARAMS)
    assert result.height == 2


def test_harsh_events_split_by_interpolated_point() -> None:
    df = _make_df(
        speed=[50.0, 61.0, 72.0, 83.0],
        is_interpolated=[False, False, True, False],
    )
    result = detect_harsh_events(df, _PARAMS)
    assert result.height == 1
    assert result["end_ts"][0] == _BASE_TS + 1


def test_harsh_accel_and_decel_are_separate_events() -> None:
    df = _make_df(speed=[50.0, 61.0, 50.0])
    result = detect_harsh_events(df, _PARAMS)
    assert result.height == 2
    types = set(result["type"].to_list())
    assert EventType.HARSH_ACCEL in types
    assert EventType.HARSH_DECEL in types


def test_harsh_events_at_exact_threshold_triggers() -> None:
    df = _make_df(speed=[50.0, 60.0])
    result = detect_harsh_events(df, _PARAMS)
    assert result.height == 1


def test_harsh_events_just_below_threshold_ignored() -> None:
    df = _make_df(speed=[50.0, 59.9])
    result = detect_harsh_events(df, _PARAMS)
    assert result.is_empty()


def test_harsh_events_do_not_cross_trip_boundary() -> None:
    df = _make_df(
        trip_id=[1, 1, 2, 2],
        ts=[_BASE_TS, _BASE_TS + 1, _BASE_TS + 2, _BASE_TS + 3],
        speed=[50.0, 61.0, 50.0, 61.0],
    )
    result = detect_harsh_events(df, _PARAMS)
    assert result.height == 2
    assert set(result["trip_id"].to_list()) == {1, 2}


# --- school zone events ---


def test_school_zone_consecutive_points_merged() -> None:
    df = _make_df(speed=[40.0, 42.0])
    hits = _zone_hits(1, [_BASE_TS, _BASE_TS + 1])
    result = detect_school_zone_events(df, hits, _PARAMS)
    assert result.height == 1
    assert result["start_ts"][0] == _BASE_TS
    assert result["end_ts"][0] == _BASE_TS + 1


def test_school_zone_split_by_max_gap() -> None:
    max_gap = _PARAMS.interp_max_gap_sec
    ts1, ts2 = _BASE_TS, _BASE_TS + max_gap + 1
    df = _make_df(ts=[ts1, ts2], speed=[40.0, 42.0])
    hits = _zone_hits(1, [ts1, ts2])
    result = detect_school_zone_events(df, hits, _PARAMS)
    assert result.height == 2


def test_school_zone_split_by_different_zones() -> None:
    df = _make_df(speed=[40.0, 40.0])
    hits = pl.DataFrame(
        {
            "trip_id": [1, 1],
            "ts": [_BASE_TS, _BASE_TS + 1],
            "zone_name": ["A초등학교", "B초등학교"],
        }
    )
    result = detect_school_zone_events(df, hits, _PARAMS)
    assert result.height == 2


def test_school_zone_shared_zone_merges_events() -> None:
    df = _make_df(speed=[40.0, 40.0])
    hits = pl.DataFrame(
        {
            "trip_id": [1, 1, 1],
            "ts": [_BASE_TS, _BASE_TS, _BASE_TS + 1],
            "zone_name": ["A초등학교", "B초등학교", "B초등학교"],
        }
    )
    result = detect_school_zone_events(df, hits, _PARAMS)
    assert result.height == 1


def test_school_zone_interpolated_point_does_not_break_group() -> None:
    df = _make_df(
        speed=[40.0, 42.0, 44.0],
        is_interpolated=[False, True, False],
    )
    hits = _zone_hits(1, [_BASE_TS, _BASE_TS + 2])
    result = detect_school_zone_events(df, hits, _PARAMS)
    assert result.height == 1
    assert result["start_ts"][0] == _BASE_TS
    assert result["end_ts"][0] == _BASE_TS + 2


def test_school_zone_normal_speed_real_point_splits_event() -> None:
    ts = [_BASE_TS, _BASE_TS + 1, _BASE_TS + 2]
    df = _make_df(ts=ts, speed=[40.0, 20.0, 40.0])
    hits = _zone_hits(1, [_BASE_TS, _BASE_TS + 2])
    result = detect_school_zone_events(df, hits, _PARAMS)
    assert result.height == 2


def test_school_zone_speed_at_limit_ignored() -> None:
    df = _make_df(speed=[30.0])
    hits = _zone_hits(1, [_BASE_TS])
    result = detect_school_zone_events(df, hits, _PARAMS)
    assert result.is_empty()


def test_school_zone_no_hits_returns_empty() -> None:
    df = _make_df(speed=[40.0])
    empty_hits = pl.DataFrame(schema={"trip_id": pl.Int64, "ts": pl.Int64, "zone_name": pl.String})
    result = detect_school_zone_events(df, empty_hits, _PARAMS)
    assert result.is_empty()
