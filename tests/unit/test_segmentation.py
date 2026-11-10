import polars as pl

from app.domain.params import AnalysisParams
from app.domain.pipeline.segmentation import assign_trip_ids, split_completed

_PARAMS = AnalysisParams()


def _make_df(vehicle_ids: list[str], timestamps: list[int]) -> pl.DataFrame:
    return pl.DataFrame({"vehicle_id": vehicle_ids, "ts": timestamps})


def test_assign_trip_ids_single_vehicle_continuous() -> None:
    df = _make_df(["V1", "V1", "V1"], [1_700_000_000, 1_700_000_001, 1_700_000_002])
    result = assign_trip_ids(df, _PARAMS)
    assert result["trip_id"].n_unique() == 1


def test_assign_trip_ids_splits_on_time_gap() -> None:
    gap = _PARAMS.trip_gap_sec
    df = _make_df(
        ["V1", "V1", "V1"],
        [1_700_000_000, 1_700_000_001, 1_700_000_001 + gap],
    )
    result = assign_trip_ids(df, _PARAMS)
    assert result["trip_id"].n_unique() == 2


def test_assign_trip_ids_splits_on_vehicle_change() -> None:
    df = _make_df(["V1", "V1", "V2"], [1_700_000_000, 1_700_000_001, 1_700_000_002])
    result = assign_trip_ids(df, _PARAMS)
    assert result["trip_id"].n_unique() == 2
    assert result["trip_id"][2] != result["trip_id"][1]


def test_assign_trip_ids_gap_just_below_threshold_no_split() -> None:
    gap = _PARAMS.trip_gap_sec
    df = _make_df(
        ["V1", "V1"],
        [1_700_000_000, 1_700_000_000 + gap - 1],
    )
    result = assign_trip_ids(df, _PARAMS)
    assert result["trip_id"].n_unique() == 1


def test_assign_trip_ids_single_record_is_one_trip() -> None:
    df = _make_df(["V1"], [1_700_000_000])
    result = assign_trip_ids(df, _PARAMS)
    assert result.height == 1
    assert result["trip_id"][0] == 1


def test_assign_trip_ids_multiple_vehicles_multiple_trips() -> None:
    gap = _PARAMS.trip_gap_sec
    df = _make_df(
        ["V1", "V1", "V2", "V2"],
        [1_700_000_000, 1_700_000_001, 1_700_000_002, 1_700_000_002 + gap],
    )
    result = assign_trip_ids(df, _PARAMS)
    assert result["trip_id"].n_unique() == 3


def test_split_completed_last_trip_is_remainder() -> None:
    df = pl.DataFrame({"trip_id": [1, 1, 2, 2, 3, 3]})
    completed, remainder = split_completed(df)
    assert completed["trip_id"].unique().sort().to_list() == [1, 2]
    assert remainder["trip_id"].unique().to_list() == [3]


def test_split_completed_single_trip_all_remainder() -> None:
    df = pl.DataFrame({"trip_id": [1, 1, 1]})
    completed, remainder = split_completed(df)
    assert completed.is_empty()
    assert remainder.height == 3


def test_split_completed_empty_df() -> None:
    df = pl.DataFrame({"trip_id": pl.Series([], dtype=pl.Int32)})
    completed, remainder = split_completed(df)
    assert completed.is_empty()
    assert remainder.is_empty()
