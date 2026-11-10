from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalysisParams:
    """파이프라인 임계값 및 설정. 파이프라인 함수에 인자로 전달한다."""

    read_chunk_size: int = 50000
    write_batch_points: int = 50000
    trip_gap_sec: int = 300
    harsh_kmh_per_sec: float = 10.0
    school_zone_speed_kmh: float = 30.0
    speed_max_kmh: float = 250.0
    spike_kmh: float = 30.0
    teleport_margin_kmh: float = 80.0
    interp_max_gap_sec: int = 10
    long_trip_warn_points: int = 100000
    lat_min: float = 33.0
    lat_max: float = 39.0
    lon_min: float = 124.0
    lon_max: float = 132.0
    ts_min: int = 946684800  # 2000-01-01 UTC, 이전 레코드는 이상치로 제거
    ts_max: int = 4102444800  # 2099-12-31 UTC, 이후 레코드는 이상치로 제거
    db_retry_max: int = 3
