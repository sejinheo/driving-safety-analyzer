from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    CheckConstraint,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("file_hash", "zone_hash", name="uq_analysis_runs_file_zone"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_hash: Mapped[str] = mapped_column(Text)
    zone_hash: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        Text,
        CheckConstraint(
            "status IN ('PENDING','INGESTING','ANALYZING','RECOVERING','COMPLETED','FAILED')",
            name="ck_analysis_runs_status",
        ),
    )
    vehicle_id_default: Mapped[str | None] = mapped_column(Text)
    ingest_next_index: Mapped[int] = mapped_column(BigInteger, server_default="0")
    analyze_last_vehicle: Mapped[str | None] = mapped_column(Text)
    analyze_last_ts: Mapped[int | None] = mapped_column(BigInteger)
    analyze_last_source_index: Mapped[int | None] = mapped_column(BigInteger)
    total_records: Mapped[int | None] = mapped_column(BigInteger)
    rejected_records: Mapped[int | None] = mapped_column(BigInteger)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trip_count: Mapped[int | None] = mapped_column(Integer)
    event_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class RawRecord(Base):
    __tablename__ = "raw_records"
    __table_args__ = (
        Index("ix_raw_records_run_vehicle_ts", "run_id", "vehicle_id", "ts", "source_index"),
    )

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analysis_runs.id"), primary_key=True
    )
    source_index: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(Text)
    ts: Mapped[int] = mapped_column(BigInteger)
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)
    speed: Mapped[float | None] = mapped_column(Double)
    speed_invalid: Mapped[bool] = mapped_column(Boolean)
    speed_out_of_range: Mapped[bool] = mapped_column(Boolean)
    gps_swapped: Mapped[bool] = mapped_column(Boolean)
    gps_invalid: Mapped[bool] = mapped_column(Boolean)


class RejectedRecord(Base):
    __tablename__ = "rejected_records"
    __table_args__ = (Index("ix_rejected_records_run_id", "run_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("analysis_runs.id"))
    source_index: Mapped[int] = mapped_column(BigInteger)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (Index("ix_trips_run_id", "run_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("analysis_runs.id"))
    vehicle_id: Mapped[str] = mapped_column(Text)
    start_ts: Mapped[int] = mapped_column(BigInteger)
    end_ts: Mapped[int] = mapped_column(BigInteger)
    duration_sec: Mapped[int] = mapped_column(Integer)
    distance_m: Mapped[float] = mapped_column(Double)
    point_count: Mapped[int] = mapped_column(Integer)
    event_count: Mapped[int] = mapped_column(Integer)
    event_counts: Mapped[dict[str, Any]] = mapped_column(JSONB)


class TripPoint(Base):
    __tablename__ = "trip_points"

    trip_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True
    )
    ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)
    speed: Mapped[float | None] = mapped_column(Double)
    is_interpolated: Mapped[bool] = mapped_column(Boolean)
    speed_invalid: Mapped[bool] = mapped_column(Boolean)
    speed_out_of_range: Mapped[bool] = mapped_column(Boolean)
    gps_swapped: Mapped[bool] = mapped_column(Boolean)
    gps_invalid: Mapped[bool] = mapped_column(Boolean)
    speed_spike: Mapped[bool] = mapped_column(Boolean)
    gps_teleport: Mapped[bool] = mapped_column(Boolean)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_trip_start_ts", "trip_id", "start_ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trip_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("trips.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(Text)
    start_ts: Mapped[int] = mapped_column(BigInteger)
    end_ts: Mapped[int] = mapped_column(BigInteger)
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB)


class SchoolZone(Base):
    __tablename__ = "school_zones"
    __table_args__ = (Index("ix_school_zones_geom", "geom", postgresql_using="gist"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)
    radius_m: Mapped[float] = mapped_column(Double)
    geom: Mapped[Any] = mapped_column(Geography(geometry_type="POINT", srid=4326))
