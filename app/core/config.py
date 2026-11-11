from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.params import AnalysisParams


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://app:app@db:5432/app"
    default_log_path: Path = Path("data/driving_log.json")
    raw_storage_dir: Path = Path("data/raw")
    max_upload_mb: int = 200

    # 파이프라인 임계값 (AnalysisParams 기본값과 동기화)
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
    ts_min: int = 946684800
    ts_max: int = 4102444800
    db_retry_max: int = 3
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10
    recovery_claim_limit: int = 100

    def to_analysis_params(self) -> AnalysisParams:
        return AnalysisParams(
            read_chunk_size=self.read_chunk_size,
            write_batch_points=self.write_batch_points,
            trip_gap_sec=self.trip_gap_sec,
            harsh_kmh_per_sec=self.harsh_kmh_per_sec,
            school_zone_speed_kmh=self.school_zone_speed_kmh,
            speed_max_kmh=self.speed_max_kmh,
            spike_kmh=self.spike_kmh,
            teleport_margin_kmh=self.teleport_margin_kmh,
            interp_max_gap_sec=self.interp_max_gap_sec,
            long_trip_warn_points=self.long_trip_warn_points,
            lat_min=self.lat_min,
            lat_max=self.lat_max,
            lon_min=self.lon_min,
            lon_max=self.lon_max,
            ts_min=self.ts_min,
            ts_max=self.ts_max,
            db_retry_max=self.db_retry_max,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
