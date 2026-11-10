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
    """원본 레코드 DataFrame을 정규화한다.

    Returns:
        (clean, rejected): clean은 정규화된 레코드, rejected는 격리된 레코드(원본 + reason 컬럼)
        clean 컬럼: vehicle_id(str), ts(i64), speed(f64|null), lat(f64|null), lon(f64|null),
                    speed_invalid(bool), speed_out_of_range(bool),
                    gps_swapped(bool), gps_invalid(bool)
    """
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
        _parse_speed_expr(params).alias("speed"),
        _speed_invalid_expr().alias("speed_invalid"),
        _speed_out_of_range_expr(params).alias("speed_out_of_range"),
    )

    df = df.with_columns(
        _gps_swapped_expr(params).alias("gps_swapped"),
    )
    df = df.with_columns(
        _apply_swap_expr().alias("lat"),
        _apply_swap_expr(swap_lon=True).alias("lon"),
    )
    df = df.with_columns(
        _gps_invalid_expr(params).alias("gps_invalid"),
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
    )

    df = df.with_columns(
        pl.col("vehicle_id").cast(pl.String).fill_null("UNKNOWN").alias("vehicle_id")
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
    numeric = pl.col("ts_raw").cast(pl.Float64, strict=False).pipe(_numeric_ts_to_epoch)
    iso = (
        pl.col("ts_raw")
        .cast(pl.String, strict=False)
        .str.replace(r"Z$", "+00:00")
        .str.to_datetime(format="%Y-%m-%dT%H:%M:%S%z", strict=False)
        .dt.epoch(time_unit="s")
    )
    is_numeric = pl.col("ts_raw").cast(pl.Float64, strict=False).is_not_null()
    return pl.when(is_numeric).then(numeric).otherwise(iso)


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


def _parse_speed_expr(params: AnalysisParams) -> pl.Expr:
    raw = pl.col("speed_raw").cast(pl.Float64, strict=False)
    return pl.when(raw.is_not_null() & (raw >= 0) & (raw <= params.speed_max_kmh)).then(raw)


def _speed_invalid_expr() -> pl.Expr:
    return (
        pl.col("speed_raw").is_not_null()
        & pl.col("speed_raw").cast(pl.Float64, strict=False).is_null()
    )


def _speed_out_of_range_expr(params: AnalysisParams) -> pl.Expr:
    raw = pl.col("speed_raw").cast(pl.Float64, strict=False)
    return raw.is_not_null() & ((raw < 0) | (raw > params.speed_max_kmh))


def _gps_swapped_expr(params: AnalysisParams) -> pl.Expr:
    lat = pl.col("lat_raw").cast(pl.Float64, strict=False)
    lon = pl.col("lon_raw").cast(pl.Float64, strict=False)
    return (
        lat.is_not_null()
        & lon.is_not_null()
        & lat.is_between(params.lon_min, params.lon_max)
        & lon.is_between(params.lat_min, params.lat_max)
    )


def _apply_swap_expr(swap_lon: bool = False) -> pl.Expr:
    lat = pl.col("lat_raw").cast(pl.Float64, strict=False)
    lon = pl.col("lon_raw").cast(pl.Float64, strict=False)
    if swap_lon:
        return pl.when(pl.col("gps_swapped")).then(lat).otherwise(lon)
    return pl.when(pl.col("gps_swapped")).then(lon).otherwise(lat)


def _gps_invalid_expr(params: AnalysisParams) -> pl.Expr:
    lat = pl.col("lat")
    lon = pl.col("lon")
    return (
        lat.is_null()
        | lon.is_null()
        | (lat == 0)
        | (lon == 0)
        | ~lat.is_between(params.lat_min, params.lat_max)
        | ~lon.is_between(params.lon_min, params.lon_max)
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
        raw = raw.strip()
        try:
            return _parse_ts_single(float(raw))
        except ValueError:
            pass
        try:
            s = raw
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return int(dt.timestamp())
        except ValueError:
            return None
    return None
