import math
from typing import Final

import polars as pl

from app.domain.enums import EventType
from app.domain.pipeline.geo import EARTH_RADIUS_M

_ALL_EVENT_TYPES: Final[tuple[str, ...]] = tuple(e.value for e in EventType)


def aggregate_trips(
    df: pl.DataFrame,
    events: pl.DataFrame,
) -> pl.DataFrame:
    trip_stats = _compute_trip_stats(df)
    event_stats = _compute_event_stats(events)
    return trip_stats.join(event_stats, on="trip_id", how="left").with_columns(
        pl.col("event_count").fill_null(0).cast(pl.Int64),
        *[pl.col(t).fill_null(0).cast(pl.Int64) for t in _ALL_EVENT_TYPES],
    )


def _haversine_per_trip(segments: pl.DataFrame) -> pl.DataFrame:
    return (
        segments.with_columns(
            (pl.col("lat") * math.pi / 180).alias("_lat1_r"),
            (pl.col("_next_lat") * math.pi / 180).alias("_lat2_r"),
            ((pl.col("_next_lat") - pl.col("lat")) * math.pi / 180).alias("_dlat"),
            ((pl.col("_next_lon") - pl.col("lon")) * math.pi / 180).alias("_dlon"),
        )
        .with_columns(
            (
                (pl.col("_dlat") / 2).sin().pow(2)
                + pl.col("_lat1_r").cos()
                * pl.col("_lat2_r").cos()
                * (pl.col("_dlon") / 2).sin().pow(2)
            ).alias("_a")
        )
        .with_columns(
            (pl.col("_a").clip(0.0, 1.0).sqrt().arcsin() * (2 * EARTH_RADIUS_M)).alias("_seg_dist")
        )
        .group_by("trip_id")
        .agg(pl.col("_seg_dist").sum().alias("_dist_m"))
    )


def _compute_trip_stats(df: pl.DataFrame) -> pl.DataFrame:
    with_next = df.with_columns(
        pl.col("lat").shift(-1).over("trip_id").alias("_next_lat"),
        pl.col("lon").shift(-1).over("trip_id").alias("_next_lon"),
    )

    has_coords = (
        pl.col("lat").is_not_null()
        & pl.col("lon").is_not_null()
        & pl.col("_next_lat").is_not_null()
        & pl.col("_next_lon").is_not_null()
    )

    segments = with_next.filter(has_coords)

    if segments.is_empty():
        dist_per_trip = pl.DataFrame(schema={"trip_id": pl.Int64, "_dist_m": pl.Float64})
    else:
        dist_per_trip = _haversine_per_trip(segments)

    trip_meta = (
        df.group_by("trip_id")
        .agg(
            pl.col("ts").min().alias("start_ts"),
            pl.col("ts").max().alias("end_ts"),
            pl.len().alias("point_count"),
        )
        .with_columns(
            (pl.col("end_ts") - pl.col("start_ts")).alias("duration_sec"),
        )
    )

    return (
        trip_meta.join(dist_per_trip, on="trip_id", how="left")
        .with_columns(pl.col("_dist_m").fill_null(0.0).alias("distance_m"))
        .drop("_dist_m")
        .select("trip_id", "start_ts", "end_ts", "duration_sec", "distance_m", "point_count")
        .cast({"trip_id": pl.Int64, "start_ts": pl.Int64, "end_ts": pl.Int64})
    )


def _compute_event_stats(events: pl.DataFrame) -> pl.DataFrame:
    if events.is_empty():
        return pl.DataFrame(
            schema={
                "trip_id": pl.Int64,
                "event_count": pl.Int64,
                **{t: pl.Int64 for t in _ALL_EVENT_TYPES},
            }
        )

    pivot = events.pivot(on="type", index="trip_id", values="type", aggregate_function="len")

    missing = [
        pl.lit(0).cast(pl.Int64).alias(t) for t in _ALL_EVENT_TYPES if t not in pivot.columns
    ]
    if missing:
        pivot = pivot.with_columns(*missing)

    return pivot.with_columns(
        pl.sum_horizontal(*[pl.col(t) for t in _ALL_EVENT_TYPES]).alias("event_count"),
    ).select("trip_id", "event_count", *_ALL_EVENT_TYPES)
