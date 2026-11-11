from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from sqlalchemy.orm import Session

from app.domain.exceptions import RunNotFoundError, TripNotFoundError
from app.main import app
from app.presentation.deps import get_session


def _mock_session() -> Iterator[Session]:
    yield MagicMock(spec=Session)


@pytest.fixture(autouse=True)
def _patch_recovery(mocker: MockerFixture) -> None:
    mocker.patch("app.main.recover_incomplete_runs")


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = _mock_session
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_unknown_route_returns_404(client: TestClient) -> None:
    response = client.get("/nonexistent")
    assert response.status_code == 404


def test_request_id_header_present(client: TestClient) -> None:
    response = client.get("/nonexistent")
    assert "x-request-id" in response.headers


def test_run_not_found_returns_domain_error(
    client: TestClient, mocker: MockerFixture
) -> None:
    mocker.patch("app.presentation.api.runs._get_run", side_effect=RunNotFoundError(999))

    response = client.get("/runs/999")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "RUN_NOT_FOUND"
    assert "request_id" in body


def test_trip_not_found_returns_domain_error(
    client: TestClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.presentation.api.trips.get_trip_detail", side_effect=TripNotFoundError(1)
    )

    response = client.get("/trips/1")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "TRIP_NOT_FOUND"
    assert "request_id" in body
