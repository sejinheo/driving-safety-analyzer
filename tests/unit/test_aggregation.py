import polars as pl
import pytest

from app.domain.enums import EventType
from app.domain.pipeline.aggregation import aggregate_trips
from app.domain.pipeline.geo import haversine_m_bruteforce

_BASE_TS = 1_700_000_000


def _make_df(**kwargs: list[object]) -> pl.DataFrame:
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


def _make_events(rows: list[dict[str, object]]) -> pl.DataFrame:
    schema = {
        "trip_id": pl.Int64,
        "type": pl.String,
        "start_ts": pl.Int64,
        "end_ts": pl.Int64,
        "lat": pl.Float64,
        "lon": pl.Float64,
        "detail": pl.String,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(
        {k: [r[k] for r in rows] for k in schema},
        schema=schema,
    )


def _ev(trip_id: int, event_type: str, offset: int = 0) -> dict[str, object]:
    return {
        "trip_id": trip_id,
        "type": event_type,
        "start_ts": _BASE_TS + offset,
        "end_ts": _BASE_TS + offset + 1,
        "lat": 37.5,
        "lon": 127.0,
        "detail": "{}",
    }


def test_duration_and_meta() -> None:
    df = _make_df(ts=[_BASE_TS, _BASE_TS + 60, _BASE_TS + 120])
    result = aggregate_trips(df, _make_events([]))
    assert result["duration_sec"][0] == 120
    assert result["point_count"][0] == 3


def test_distance_m_matches_haversine() -> None:
    lat1, lon1 = 37.5, 127.0
    lat2, lon2 = 37.6, 127.1
    df = _make_df(lat=[lat1, lat2], lon=[lon1, lon2])
    result = aggregate_trips(df, _make_events([]))
    expected = haversine_m_bruteforce(lat1, lon1, lat2, lon2)
    assert result["distance_m"][0] == pytest.approx(expected, rel=1e-6)


def test_distance_m_null_coord_segment_not_counted() -> None:
    lat1, lon1 = 37.5, 127.0
    lat2, lon2 = 37.6, 127.1
    # 세 포인트 중 중간이 null → (p0→p1), (p1→p2) 두 세그먼트 모두 null 포함으로 제외
    # 결과는 직접 연결되는 세그먼트가 없어 distance=0
    df = _make_df(lat=[lat1, None, lat2], lon=[lon1, None, lon2])
    result = aggregate_trips(df, _make_events([]))
    assert result["distance_m"][0] == pytest.approx(0.0)


def test_distance_m_single_point_trip() -> None:
    df = _make_df(lat=[37.5], lon=[127.0], ts=[_BASE_TS])
    result = aggregate_trips(df, _make_events([]))
    assert result["distance_m"][0] == pytest.approx(0.0)
    assert result["duration_sec"][0] == 0


def test_event_counts_all_types() -> None:
    events = _make_events(
        [
            _ev(1, EventType.HARSH_ACCEL, 0),
            _ev(1, EventType.HARSH_ACCEL, 2),
            _ev(1, EventType.SCHOOL_ZONE_SPEEDING, 4),
        ]
    )
    df = _make_df(ts=list(range(_BASE_TS, _BASE_TS + 6)))
    result = aggregate_trips(df, events)
    assert result["event_count"][0] == 3
    assert result[EventType.HARSH_ACCEL][0] == 2
    assert result[EventType.HARSH_DECEL][0] == 0
    assert result[EventType.SCHOOL_ZONE_SPEEDING][0] == 1


def test_event_counts_zero_when_no_events() -> None:
    df = _make_df(ts=[_BASE_TS, _BASE_TS + 1])
    result = aggregate_trips(df, _make_events([]))
    assert result["event_count"][0] == 0
    for t in EventType:
        assert result[t.value][0] == 0


def test_multiple_trips_aggregated_independently() -> None:
    df = _make_df(
        trip_id=[1, 1, 2, 2],
        ts=[_BASE_TS, _BASE_TS + 10, _BASE_TS + 20, _BASE_TS + 30],
        lat=[37.5, 37.6, 37.7, 37.8],
        lon=[127.0, 127.1, 127.2, 127.3],
    )
    events = _make_events([_ev(1, EventType.HARSH_ACCEL)])
    result = aggregate_trips(df, events).sort("trip_id")
    assert result.height == 2
    assert result.filter(pl.col("trip_id") == 1)["event_count"][0] == 1
    assert result.filter(pl.col("trip_id") == 2)["event_count"][0] == 0
