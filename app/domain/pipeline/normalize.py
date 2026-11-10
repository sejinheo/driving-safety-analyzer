import math
from datetime import UTC, datetime

import polars as pl

from app.domain.params import AnalysisParams

_TS_MILLI_THRESHOLD: float = 1e11
_TS_MICRO_THRESHOLD: float = 1e14
_TS_NANO_THRESHOLD: float = 1e17


def normalize(
    df: pl.DataFrame,
    params: AnalysisParams,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    rejected_frames: list[pl.DataFrame] = []

    df, rej = _reject(df, pl.col("ts_raw").is_null(), "MISSING_TIMESTAMP")
    rejected_frames.append(rej)

    df = df.with_columns(_parse_ts_expr().alias("ts"))

    df, rej = _reject(df, pl.col("ts").is_null(), "INVALID_TIMESTAMP")
    rejected_frames.append(rej)

    df, rej = _reject(
        df,
        (pl.col("ts") < params.ts_min) | (pl.col("ts") > params.ts_max),
        "TIMESTAMP_OUT_OF_RANGE",
    )
    rejected_frames.append(rej)

    df = df.with_columns(
        pl.col("speed_raw").cast(pl.Float64, strict=False).alias("_speed"),
        pl.col("lat_raw").cast(pl.Float64, strict=False).alias("_lat"),
        pl.col("lon_raw").cast(pl.Float64, strict=False).alias("_lon"),
    )

    df = df.with_columns(
        pl.when(
            pl.col("_speed").is_not_null()
            & (pl.col("_speed") >= 0)
            & (pl.col("_speed") <= params.speed_max_kmh)
        )
        .then(pl.col("_speed"))
        .alias("speed"),
        (pl.col("speed_raw").is_not_null() & pl.col("_speed").is_null()).alias("speed_invalid"),
        (
            pl.col("_speed").is_not_null()
            & ((pl.col("_speed") < 0) | (pl.col("_speed") > params.speed_max_kmh))
        ).alias("speed_out_of_range"),
        (
            pl.col("_lat").is_not_null()
            & pl.col("_lon").is_not_null()
            & pl.col("_lat").is_between(params.lon_min, params.lon_max)
            & pl.col("_lon").is_between(params.lat_min, params.lat_max)
        ).alias("gps_swapped"),
    )

    df = df.with_columns(
        pl.when(pl.col("gps_swapped")).then(pl.col("_lon")).otherwise(pl.col("_lat")).alias("lat"),
        pl.when(pl.col("gps_swapped")).then(pl.col("_lat")).otherwise(pl.col("_lon")).alias("lon"),
    )

    df = df.with_columns(
        (
            pl.col("lat").is_null()
            | pl.col("lon").is_null()
            | (pl.col("lat") == 0)
            | (pl.col("lon") == 0)
            | ~pl.col("lat").is_between(params.lat_min, params.lat_max)
            | ~pl.col("lon").is_between(params.lon_min, params.lon_max)
        ).alias("gps_invalid"),
    )

    df = df.with_columns(
        pl.when(pl.col("gps_invalid"))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("lat"))
        .alias("lat"),
        pl.when(pl.col("gps_invalid"))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("lon"))
        .alias("lon"),
        pl.col("vehicle_id").cast(pl.String).fill_null("UNKNOWN").alias("vehicle_id"),
    )

    clean = df.select(
        "vehicle_id",
        "ts",
        "speed",
        "lat",
        "lon",
        "speed_invalid",
        "speed_out_of_range",
        "gps_swapped",
        "gps_invalid",
    )

    non_empty = [f for f in rejected_frames if f.height > 0]
    rejected = pl.concat(non_empty) if non_empty else pl.DataFrame()

    return clean, rejected


def _reject(
    df: pl.DataFrame,
    mask: pl.Expr,
    reason: str,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    rejected = df.filter(mask).with_columns(pl.lit(reason).alias("reason"))
    clean = df.filter(~mask)
    return clean, rejected


def _parse_ts_expr() -> pl.Expr:
    ts_float = pl.col("ts_raw").cast(pl.Float64, strict=False)
    numeric = ts_float.pipe(_numeric_ts_to_epoch)
    iso = (
        pl.col("ts_raw")
        .cast(pl.String, strict=False)
        .str.replace(r"Z$", "+00:00")
        .str.to_datetime(format="%Y-%m-%dT%H:%M:%S%z", strict=False)
        .dt.epoch(time_unit="s")
    )
    return pl.when(ts_float.is_not_null()).then(numeric).otherwise(iso)


def _numeric_ts_to_epoch(expr: pl.Expr) -> pl.Expr:
    abs_val = expr.abs()
    return (
        pl.when(abs_val < _TS_MILLI_THRESHOLD)
        .then(expr)
        .when(abs_val < _TS_MICRO_THRESHOLD)
        .then(expr / 1e3)
        .when(abs_val < _TS_NANO_THRESHOLD)
        .then(expr / 1e6)
        .otherwise(expr / 1e9)
        .cast(pl.Int64, strict=False)
    )


def _parse_ts_single(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
        if math.isnan(v) or math.isinf(v):
            return None
        a = abs(v)
        if a < _TS_MILLI_THRESHOLD:
            return int(v)
        if a < _TS_MICRO_THRESHOLD:
            return int(v / 1e3)
        if a < _TS_NANO_THRESHOLD:
            return int(v / 1e6)
        return int(v / 1e9)
    if isinstance(raw, str):
        s = raw.strip()
        try:
            return _parse_ts_single(float(s))
        except ValueError:
            pass
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp())
        except ValueError:
            return None
    return None
