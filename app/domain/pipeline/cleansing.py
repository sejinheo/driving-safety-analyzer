import polars as pl

from app.domain.params import AnalysisParams
from app.domain.pipeline.geo import haversine_expr


def merge_duplicates(df: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    before = df.height

    merged = (
        df.group_by("vehicle_id", "ts")
        .agg(
            pl.col("source_index").min(),
            pl.col("speed").drop_nulls().mean(),
            pl.col("lat").drop_nulls().mean(),
            pl.col("lon").drop_nulls().mean(),
            pl.col("speed_invalid").any(),
            pl.col("speed_out_of_range").any(),
            pl.col("gps_swapped").any(),
            pl.col("gps_invalid").any(),
        )
        .sort("vehicle_id", "ts")
    )

    return merged, before - merged.height


def remove_speed_spikes(df: pl.DataFrame, params: AnalysisParams) -> pl.DataFrame:
    spike = params.spike_kmh
    half_spike = spike / 2

    df = df.with_columns(
        pl.col("speed").shift(1).over("trip_id").alias("_prev_speed"),
        pl.col("speed").shift(-1).over("trip_id").alias("_next_speed"),
        pl.col("ts").shift(1).over("trip_id").alias("_prev_ts"),
        pl.col("ts").shift(-1).over("trip_id").alias("_next_ts"),
    )

    is_spike = (
        pl.col("speed").is_not_null()
        & pl.col("_prev_speed").is_not_null()
        & pl.col("_next_speed").is_not_null()
        & ((pl.col("ts") - pl.col("_prev_ts")) == 1)
        & ((pl.col("_next_ts") - pl.col("ts")) == 1)
        & ((pl.col("speed") - pl.col("_prev_speed")).abs() > spike)
        & ((pl.col("speed") - pl.col("_next_speed")).abs() > spike)
        & ((pl.col("_prev_speed") - pl.col("_next_speed")).abs() <= half_spike)
    )

    return df.with_columns(
        pl.when(is_spike)
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("speed"))
        .alias("speed"),
        is_spike.alias("speed_spike"),
    ).drop("_prev_speed", "_next_speed", "_prev_ts", "_next_ts")


def remove_gps_teleports(df: pl.DataFrame, params: AnalysisParams) -> pl.DataFrame:
    margin = params.teleport_margin_kmh

    df = df.with_columns(
        pl.col("lat").shift(1).over("trip_id").alias("_prev_lat"),
        pl.col("lon").shift(1).over("trip_id").alias("_prev_lon"),
        pl.col("lat").shift(-1).over("trip_id").alias("_next_lat"),
        pl.col("lon").shift(-1).over("trip_id").alias("_next_lon"),
        pl.col("ts").shift(1).over("trip_id").alias("_prev_ts"),
        pl.col("ts").shift(-1).over("trip_id").alias("_next_ts"),
        pl.col("speed").shift(1).over("trip_id").alias("_prev_speed"),
        pl.col("speed").shift(-1).over("trip_id").alias("_next_speed"),
    )

    dt_prev = (pl.col("ts") - pl.col("_prev_ts")).cast(pl.Float64)
    dt_next = (pl.col("_next_ts") - pl.col("ts")).cast(pl.Float64)

    lat, lon = pl.col("lat"), pl.col("lon")
    dist_prev = haversine_expr(lat, lon, pl.col("_prev_lat"), pl.col("_prev_lon"))
    dist_next = haversine_expr(lat, lon, pl.col("_next_lat"), pl.col("_next_lon"))

    gps_speed_prev = pl.when(dt_prev > 0).then(dist_prev / dt_prev * 3.6)
    gps_speed_next = pl.when(dt_next > 0).then(dist_next / dt_next * 3.6)

    speed = pl.col("speed").fill_null(0.0)
    sensor_max_prev = pl.max_horizontal(speed, pl.col("_prev_speed").fill_null(0.0))
    sensor_max_next = pl.max_horizontal(speed, pl.col("_next_speed").fill_null(0.0))

    has_coords = pl.col("lat").is_not_null() & pl.col("lon").is_not_null()
    has_prev = pl.col("_prev_lat").is_not_null() & pl.col("_prev_lon").is_not_null()
    has_next = pl.col("_next_lat").is_not_null() & pl.col("_next_lon").is_not_null()

    teleport_via_prev = (
        has_coords
        & has_prev
        & dt_prev.is_between(1, 2)
        & ((gps_speed_prev - sensor_max_prev) > margin)
        & (dist_prev >= pl.when(has_next).then(dist_next).otherwise(0.0))
    )
    teleport_via_next = (
        has_coords
        & has_next
        & dt_next.is_between(1, 2)
        & ((gps_speed_next - sensor_max_next) > margin)
        & (dist_next >= pl.when(has_prev).then(dist_prev).otherwise(0.0))
    )

    is_teleport = teleport_via_prev | teleport_via_next

    return df.with_columns(
        pl.when(is_teleport)
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("lat"))
        .alias("lat"),
        pl.when(is_teleport)
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("lon"))
        .alias("lon"),
        is_teleport.alias("gps_teleport"),
    ).drop(
        "_prev_lat",
        "_prev_lon",
        "_next_lat",
        "_next_lon",
        "_prev_ts",
        "_next_ts",
        "_prev_speed",
        "_next_speed",
    )
