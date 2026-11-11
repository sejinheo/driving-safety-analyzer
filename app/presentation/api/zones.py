import ijson  # type: ignore[import-untyped]
from fastapi import APIRouter, UploadFile

from app.application import zone_usecase
from app.application.dto.zone_dto import ZoneResponse
from app.domain.exceptions import InvalidLogFormatError, InvalidZoneDataError
from app.presentation.deps import ConnDep, ParamsDep

router = APIRouter()


@router.post("/zones", response_model=ZoneResponse)
def register_zones(
    conn: ConnDep,
    params: ParamsDep,
    file: UploadFile,
) -> ZoneResponse:
    try:
        raw: list[dict[str, object]] = []
        non_dict_indices: list[int] = []
        for i, item in enumerate(ijson.items(file.file, "item")):
            if not isinstance(item, dict):
                non_dict_indices.append(i)
            else:
                raw.append(item)
    except ijson.JSONError as exc:
        raise InvalidLogFormatError(str(exc)) from exc

    if non_dict_indices:
        raise InvalidZoneDataError(f"index {non_dict_indices[:5]} 항목이 객체가 아닙니다")

    inserted = zone_usecase.register_zones(conn, raw=raw, params=params)
    return ZoneResponse(inserted=inserted)
