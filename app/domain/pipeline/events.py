import polars as pl

from app.domain.enums import EventType
from app.domain.params import AnalysisParams

_EVENT_SCHEMA = {
    "trip_id": pl.Int64,
    "type": pl.String,
    "start_ts": pl.Int64,
    "end_ts": pl.Int64,
    "lat": pl.Float64,
    "lon": pl.Float64,
    "detail": pl.String,
}


def detect_harsh_events(df: pl.DataFrame, params: AnalysisParams) -> pl.DataFrame:
    threshold = params.harsh_kmh_per_sec

    candidates = (
        df.with_columns(
            pl.col("ts").shift(-1).over("trip_id").alias("_next_ts"),
            pl.col("speed").shift(-1).over("trip_id").alias("_next_speed"),
            pl.col("lat").alias("_start_lat"),
            pl.col("lon").alias("_start_lon"),
            pl.col("is_interpolated").shift(-1).over("trip_id").alias("_next_interp"),
        )
        .filter(
            pl.col("_next_ts").is_not_null()
            & (pl.col("_next_ts") - pl.col("ts") == 1)
            & ~pl.col("is_interpolated")
            & ~pl.col("_next_interp")
            & pl.col("speed").is_not_null()
            & pl.col("_next_speed").is_not_null()
        )
        .with_columns((pl.col("_next_speed") - pl.col("speed")).alias("_diff"))
        .filter((pl.col("_diff") >= threshold) | (pl.col("_diff") <= -threshold))
        .with_columns(
            pl.when(pl.col("_diff") >= threshold)
            .then(pl.lit(EventType.HARSH_ACCEL))
            .otherwise(pl.lit(EventType.HARSH_DECEL))
            .alias("_event_type")
        )
    )

    if candidates.is_empty():
        return pl.DataFrame(schema=_EVENT_SCHEMA)

    return _group_harsh_pairs(candidates)


def detect_school_zone_events(
    df: pl.DataFrame,
    zone_hits: pl.DataFrame,
    params: AnalysisParams,
) -> pl.DataFrame:
    max_gap = params.interp_max_gap_sec
    speed_limit = params.school_zone_speed_kmh

    if zone_hits.is_empty():
        return pl.DataFrame(schema=_EVENT_SCHEMA)

    zone_sets = zone_hits.group_by("trip_id", "ts").agg(
        pl.col("zone_name").unique().sort().alias("zones")
    )

    speeding = df.filter(
        ~pl.col("is_interpolated")
        & pl.col("speed").is_not_null()
        & (pl.col("speed") > speed_limit)
        & pl.col("lat").is_not_null()
        & pl.col("lon").is_not_null()
    ).join(zone_sets, on=["trip_id", "ts"], how="inner")

    if speeding.is_empty():
        return pl.DataFrame(schema=_EVENT_SCHEMA)

    real_non_speeding = df.filter(
        ~pl.col("is_interpolated") & (pl.col("speed").is_null() | (pl.col("speed") <= speed_limit))
    ).select("trip_id", "ts")

    return _group_zone_pairs(speeding, real_non_speeding, max_gap)


def _group_harsh_pairs(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.sort("trip_id", "ts")
        .with_columns(
            (
                (pl.col("_event_type") != pl.col("_event_type").shift(1).over("trip_id"))
                | (pl.col("ts") != pl.col("ts").shift(1).over("trip_id") + 1)
                | (pl.col("trip_id") != pl.col("trip_id").shift(1))
            )
            .fill_null(True)
            .cum_sum()
            .alias("_group_id")
        )
        .group_by("_group_id")
        .agg(
            pl.col("trip_id").first(),
            pl.col("_event_type").first().alias("type"),
            pl.col("ts").min().alias("start_ts"),
            pl.col("_next_ts").max().alias("end_ts"),
            pl.col("_start_lat").first().alias("lat"),
            pl.col("_start_lon").first().alias("lon"),
            pl.col("_diff").abs().max().alias("_max_change"),
        )
        .with_columns(
            pl.struct(max_change_kmh=pl.col("_max_change")).struct.json_encode().alias("detail")
        )
        .select(list(_EVENT_SCHEMA.keys()))
        .cast({"trip_id": pl.Int64, "start_ts": pl.Int64, "end_ts": pl.Int64})
        .sort("start_ts")
    )


def _group_zone_pairs(
    df: pl.DataFrame,
    real_non_speeding: pl.DataFrame,
    max_gap: int,
) -> pl.DataFrame:
    sorted_df = df.sort("trip_id", "ts")

    prev_speeding = sorted_df.select(
        pl.col("trip_id"),
        pl.col("ts").alias("sp_ts"),
        pl.col("ts").shift(1).over("trip_id").alias("sp_prev_ts"),
    )

    blocked_ts = (
        real_non_speeding.sort("ts")
        .with_columns(pl.col("ts").set_sorted())
        .join_asof(
            prev_speeding.sort("sp_ts").with_columns(pl.col("sp_ts").set_sorted()),
            left_on="ts",
            right_on="sp_ts",
            by="trip_id",
            strategy="forward",
        )
        .filter(pl.col("sp_prev_ts").is_not_null() & (pl.col("ts") > pl.col("sp_prev_ts")))
        .select(pl.col("trip_id"), pl.col("sp_ts").alias("ts"))
        .unique()
        .with_columns(pl.lit(True).alias("_blocked"))
    )

    return (
        sorted_df.join(blocked_ts, on=["trip_id", "ts"], how="left")
        .with_columns(pl.col("_blocked").fill_null(False))
        .with_columns(pl.col("zones").shift(1).over("trip_id").alias("_prev_zones"))
        .with_columns(
            (
                (pl.col("ts") - pl.col("ts").shift(1).over("trip_id") > max_gap)
                | (pl.col("trip_id") != pl.col("trip_id").shift(1))
                | pl.col("_blocked")
                | pl.when(pl.col("_prev_zones").is_null())
                .then(pl.lit(False))
                .otherwise(
                    pl.col("zones").list.set_intersection(pl.col("_prev_zones")).list.len() == 0
                )
            )
            .fill_null(True)
            .cum_sum()
            .alias("_group_id")
        )
        .group_by("_group_id")
        .agg(
            pl.col("trip_id").first(),
            pl.col("ts").min().alias("start_ts"),
            pl.col("ts").max().alias("end_ts"),
            pl.col("lat").first().alias("lat"),
            pl.col("lon").first().alias("lon"),
            pl.col("speed").max().alias("_max_speed"),
            pl.col("zones").explode().unique().sort().alias("_zone_names"),
        )
        .with_columns(
            pl.lit(EventType.SCHOOL_ZONE_SPEEDING).alias("type"),
            pl.struct(
                max_speed_kmh=pl.col("_max_speed"),
                zones=pl.col("_zone_names").list.join(","),
            )
            .struct.json_encode()
            .alias("detail"),
        )
        .select(list(_EVENT_SCHEMA.keys()))
        .cast({"trip_id": pl.Int64, "start_ts": pl.Int64, "end_ts": pl.Int64})
        .sort("start_ts")
    )
