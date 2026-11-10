import polars as pl

from app.domain.params import AnalysisParams


def assign_trip_ids(df: pl.DataFrame, params: AnalysisParams) -> pl.DataFrame:
    gap = params.trip_gap_sec

    is_new_trip = (
        (pl.col("vehicle_id") != pl.col("vehicle_id").shift(1))
        | (pl.col("ts") - pl.col("ts").shift(1) >= gap)
    ).fill_null(True)

    return df.with_columns(is_new_trip.cum_sum().alias("trip_id"))


def split_completed(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    if df.is_empty():
        return df, df

    last_trip_id = df["trip_id"][-1]
    completed = df.filter(pl.col("trip_id") < last_trip_id)
    remainder = df.filter(pl.col("trip_id") == last_trip_id)
    return completed, remainder
