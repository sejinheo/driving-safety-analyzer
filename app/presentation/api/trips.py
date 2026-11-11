from fastapi import APIRouter

from app.application.dto.trip_dto import TripDetailResponse
from app.application.trip_query import get_trip_detail
from app.presentation.deps import SessionDep

router = APIRouter()


@router.get("/trips/{trip_id}", response_model=TripDetailResponse)
def get_trip(trip_id: int, session: SessionDep) -> TripDetailResponse:
    return get_trip_detail(session, trip_id=trip_id)
