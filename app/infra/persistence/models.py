from datetime import datetime
from typing import Any

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_hash: Mapped[str] = mapped_column(Text, unique=True)
    file_path: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        Text,
        CheckConstraint(
            "status IN ('PENDING','INGESTING','ANALYZING','COMPLETED','FAILED')",
            name="ck_analysis_runs_status",
        ),
    )
    vehicle_id_default: Mapped[str | None] = mapped_column(Text)
    ingest_next_index: Mapped[int] = mapped_column(BigInteger, server_default="0")
    analyze_last_vehicle: Mapped[str | None] = mapped_column(Text)
    analyze_last_ts: Mapped[int | None] = mapped_column(BigInteger)
    total_records: Mapped[int | None] = mapped_column(BigInteger)
    rejected_records: Mapped[int | None] = mapped_column(BigInteger)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trip_count: Mapped[int | None] = mapped_column(Integer)
    event_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class RawRecord(Base):
    __tablename__ = "raw_records"
    __table_args__ = (Index("ix_raw_records_run_vehicle_ts", "run_id", "vehicle_id", "ts"),)

    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("analysis_runs.id"), primary_key=True
    )
    source_index: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(Text)
    ts: Mapped[int] = mapped_column(BigInteger)
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)
    speed: Mapped[float | None] = mapped_column(Double)
    cell_key: Mapped[int | None] = mapped_column(BigInteger)
    speed_invalid: Mapped[bool] = mapped_column(Boolean)
    speed_out_of_range: Mapped[bool] = mapped_column(Boolean)
    gps_swapped: Mapped[bool] = mapped_column(Boolean)
    gps_invalid: Mapped[bool] = mapped_column(Boolean)


class RejectedRecord(Base):
    __tablename__ = "rejected_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("analysis_runs.id"))
    source_index: Mapped[int] = mapped_column(BigInteger)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)


class Trip(Base):
    __tablename__ = "trips"

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
    __table_args__ = (Index("ix_trip_points_trip_ts", "trip_id", "ts"),)

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
    __table_args__ = (Index("ix_events_trip_id", "trip_id"),)

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

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)
    radius_m: Mapped[float] = mapped_column(Double)
