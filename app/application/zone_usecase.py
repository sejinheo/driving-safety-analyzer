from psycopg import Connection

from app.domain.exceptions import InvalidZoneDataError
from app.domain.params import AnalysisParams
from app.domain.zone import load_zones
from app.infra.persistence import zone_repository


def register_zones(
    conn: Connection,
    *,
    raw: list[dict[str, object]],
    params: AnalysisParams,
) -> int:
    try:
        zones = load_zones(raw, params)
    except ValueError as exc:
        raise InvalidZoneDataError(str(exc)) from exc
    return zone_repository.replace_all(conn, zones=zones)
