from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.params import AnalysisParams


@dataclass(frozen=True, slots=True)
class Zone:
    lat: float
    lon: float
    radius_m: float
    names: tuple[str, ...]


def load_zones(
    raw: list[dict[str, object]],
    params: AnalysisParams,
) -> list[Zone]:
    merged: dict[tuple[float, float], _MergeEntry] = {}

    for item in raw:
        name = str(item.get("name", ""))
        lat = _to_float(item.get("lat") or item.get("gps_lat"))
        lon = _to_float(item.get("lon") or item.get("gps_lon"))
        radius_m = _to_float(item.get("radius_m") or item.get("radius_meters"))

        if lat is None or lon is None:
            continue
        if radius_m is None or radius_m <= 0:
            continue
        if not (params.lat_min <= lat <= params.lat_max):
            continue
        if not (params.lon_min <= lon <= params.lon_max):
            continue

        key = (lat, lon)
        if key in merged:
            merged[key].names.append(name)
        else:
            merged[key] = _MergeEntry(lat=lat, lon=lon, radius_m=radius_m, names=[name])

    if not merged:
        raise ValueError("유효한 보호구역이 없습니다")

    return [
        Zone(lat=e.lat, lon=e.lon, radius_m=e.radius_m, names=tuple(e.names))
        for e in merged.values()
    ]


@dataclass
class _MergeEntry:
    lat: float
    lon: float
    radius_m: float
    names: list[str] = field(default_factory=list)


def _to_float(val: object) -> float | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float, str, Decimal)):
        try:
            return float(val)
        except ValueError:
            return None
    return None
