import polars as pl

from app.domain.params import AnalysisParams

_TEMP_COLS = ("_next_ts", "_next_lat", "_next_lon", "_next_speed")
_INTERP_COLS = ("speed", "lat", "lon")


def interpolate_values(df: pl.DataFrame, params: AnalysisParams) -> pl.DataFrame:
    max_gap = params.interp_max_gap_sec

    if "is_interpolated" not in df.columns:
        df = df.with_columns(pl.lit(False).alias("is_interpolated"))

    df = df.with_columns(
        _linear_interp_expr(col, max_gap).alias(f"_filled_{col}") for col in _INTERP_COLS
    )

    was_interpolated = pl.lit(False)
    for col in _INTERP_COLS:
        was_interpolated = was_interpolated | (
            pl.col(col).is_null() & pl.col(f"_filled_{col}").is_not_null()
        )

    df = df.with_columns(
        *(pl.col(f"_filled_{col}").alias(col) for col in _INTERP_COLS),
        (pl.col("is_interpolated") | was_interpolated).alias("is_interpolated"),
    )

    return df.drop(f"_filled_{col}" for col in _INTERP_COLS)


def interpolate_rows(df: pl.DataFrame, params: AnalysisParams) -> pl.DataFrame:
    max_gap = params.interp_max_gap_sec

    if "is_interpolated" not in df.columns:
        df = df.with_columns(pl.lit(False).alias("is_interpolated"))

    df = df.with_columns(
        pl.col("ts").shift(-1).over("trip_id").alias("_next_ts"),
        pl.col("lat").shift(-1).over("trip_id").alias("_next_lat"),
        pl.col("lon").shift(-1).over("trip_id").alias("_next_lon"),
        pl.col("speed").shift(-1).over("trip_id").alias("_next_speed"),
    )

    gap_mask = pl.col("_next_ts").is_not_null() & (pl.col("_next_ts") - pl.col("ts")).is_between(
        2, max_gap
    )

    gaps = df.filter(gap_mask)
    base = df.drop(*_TEMP_COLS)

    if gaps.is_empty():
        return base

    new_rows = (
        gaps.with_columns(pl.int_ranges(pl.col("ts") + 1, pl.col("_next_ts")).alias("_interp_ts"))
        .explode("_interp_ts")
        .with_columns(
            (
                (pl.col("_interp_ts") - pl.col("ts")).cast(pl.Float64)
                / (pl.col("_next_ts") - pl.col("ts")).cast(pl.Float64)
            ).alias("_frac")
        )
        .with_columns(
            pl.col("_interp_ts").alias("ts"),
            (pl.col("lat") + (pl.col("_next_lat") - pl.col("lat")) * pl.col("_frac")).alias("lat"),
            (pl.col("lon") + (pl.col("_next_lon") - pl.col("lon")) * pl.col("_frac")).alias("lon"),
            (pl.col("speed") + (pl.col("_next_speed") - pl.col("speed")) * pl.col("_frac")).alias(
                "speed"
            ),
            pl.lit(True).alias("is_interpolated"),
            pl.lit(False).alias("speed_invalid"),
            pl.lit(False).alias("speed_out_of_range"),
            pl.lit(False).alias("gps_swapped"),
            pl.lit(False).alias("gps_invalid"),
            pl.lit(False).alias("speed_spike"),
            pl.lit(False).alias("gps_teleport"),
        )
        .select(base.columns)
    )

    return pl.concat([base, new_rows]).sort("vehicle_id", "ts", "trip_id")


def _linear_interp_expr(col: str, max_gap: int) -> pl.Expr:
    val = pl.col(col)
    ts = pl.col("ts")

    valid_ts = pl.when(val.is_not_null()).then(ts)
    prev_valid_ts = valid_ts.forward_fill().over("trip_id")
    next_valid_ts = valid_ts.backward_fill().over("trip_id")

    prev_val = val.forward_fill().over("trip_id")
    next_val = val.backward_fill().over("trip_id")

    gap_ok = (next_valid_ts - prev_valid_ts) <= max_gap
    has_neighbors = prev_val.is_not_null() & next_val.is_not_null()

    frac = (ts - prev_valid_ts).cast(pl.Float64) / (next_valid_ts - prev_valid_ts).cast(pl.Float64)
    interpolated = prev_val + frac * (next_val - prev_val)

    return pl.when(val.is_not_null()).then(val).when(has_neighbors & gap_ok).then(interpolated)
