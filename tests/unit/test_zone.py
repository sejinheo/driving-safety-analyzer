from decimal import Decimal

import pytest

from app.domain.params import AnalysisParams
from app.domain.zone import load_zones


def _params() -> AnalysisParams:
    return AnalysisParams()


def test_load_zones_decimal_values_from_ijson() -> None:
    raw = [
        {
            "name": "광장초등학교",
            "gps_lat": Decimal("37.5485492"),
            "gps_lon": Decimal("127.1017999"),
            "radius_meters": 300,
        }
    ]
    zones = load_zones(raw, _params())
    assert len(zones) == 1
    assert pytest.approx(zones[0].lat, rel=1e-6) == 37.5485492
    assert pytest.approx(zones[0].lon, rel=1e-6) == 127.1017999


def test_load_zones_float_and_str_values() -> None:
    raw = [
        {"name": "A", "lat": 37.5, "lon": 127.0, "radius_m": 300.0},
        {"name": "B", "lat": "37.6", "lon": "127.1", "radius_m": "200"},
    ]
    zones = load_zones(raw, _params())
    assert len(zones) == 2


def test_load_zones_missing_coords_skipped() -> None:
    raw = [
        {"name": "no_lat", "lon": 127.0, "radius_m": 300},
        {"name": "no_lon", "lat": 37.5, "radius_m": 300},
        {"name": "valid", "lat": 37.5, "lon": 127.0, "radius_m": 300},
    ]
    zones = load_zones(raw, _params())
    assert len(zones) == 1


def test_load_zones_out_of_range_skipped() -> None:
    raw = [
        {"name": "overseas", "lat": 35.0, "lon": 139.0, "radius_m": 300},
        {"name": "valid", "lat": 37.5, "lon": 127.0, "radius_m": 300},
    ]
    zones = load_zones(raw, _params())
    assert len(zones) == 1


def test_load_zones_empty_raises() -> None:
    with pytest.raises(ValueError, match="유효한 보호구역이 없습니다"):
        load_zones([], _params())


def test_load_zones_all_invalid_raises() -> None:
    raw = [{"name": "bad", "lat": None, "lon": None, "radius_m": 300}]
    with pytest.raises(ValueError, match="유효한 보호구역이 없습니다"):
        load_zones(raw, _params())
