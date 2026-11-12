from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from app.application import analyze_service
from app.application.dto.analyze_dto import AcceptedResponse
from app.domain.enums import RunStatus
from app.domain.params import AnalysisParams


def _make_run(*, status: RunStatus, run_id: int = 1) -> MagicMock:
    run = MagicMock()
    run.id = run_id
    run.status = status
    return run


def _make_params() -> AnalysisParams:
    return AnalysisParams()


@pytest.fixture()
def default_log(tmp_path: Path) -> Path:
    p = tmp_path / "driving_log.json"
    p.write_text('[{"vehicle_id":"V1","ts":1,"speed":50,"lat":37.5,"lon":127.0}]')
    return p


@pytest.fixture()
def empty_log(tmp_path: Path) -> Path:
    p = tmp_path / "empty.json"
    p.write_text("")
    return p


@pytest.mark.anyio
async def test_accept_new_run_returns_pending_and_registers_background_task(
    default_log: Path, mocker: MockerFixture
) -> None:
    run = _make_run(status=RunStatus.PENDING)
    bt = MagicMock()
    mocker.patch("app.application.analyze_service._hash_file", return_value="abc123")
    mocker.patch("app.infra.persistence.run_repository.create_run", return_value=run)
    mocker.patch("app.application.analyze_service.get_current_zone_hash", return_value="zh1")
    mocker.patch("app.application.analyze_service.asyncio.to_thread", side_effect=_fake_to_thread)

    result = await analyze_service.accept(
        stream=None,
        vehicle_id_query=None,
        background_tasks=bt,
        session=MagicMock(),
        conn=MagicMock(),
        pool=MagicMock(),
        session_factory=MagicMock(),
        params=_make_params(),
        storage_dir=default_log.parent,
        default_log_path=default_log,
        max_upload_mb=10,
    )

    assert isinstance(result, AcceptedResponse)
    assert result.status == RunStatus.PENDING
    bt.add_task.assert_called_once()


@pytest.mark.anyio
async def test_accept_completed_run_skips_background_task(
    default_log: Path, mocker: MockerFixture
) -> None:
    run = _make_run(status=RunStatus.COMPLETED)
    bt = MagicMock()
    mocker.patch("app.application.analyze_service._hash_file", return_value="abc123")
    mocker.patch("app.infra.persistence.run_repository.create_run", return_value=run)
    mocker.patch("app.application.analyze_service.get_current_zone_hash", return_value="zh1")
    mocker.patch("app.application.analyze_service.asyncio.to_thread", side_effect=_fake_to_thread)

    result = await analyze_service.accept(
        stream=None,
        vehicle_id_query=None,
        background_tasks=bt,
        session=MagicMock(),
        conn=MagicMock(),
        pool=MagicMock(),
        session_factory=MagicMock(),
        params=_make_params(),
        storage_dir=default_log.parent,
        default_log_path=default_log,
        max_upload_mb=10,
    )

    assert result.status == RunStatus.COMPLETED
    bt.add_task.assert_not_called()


@pytest.mark.anyio
async def test_accept_empty_default_log_raises(empty_log: Path) -> None:
    from app.domain.exceptions import EmptyLogFileError

    with pytest.raises(EmptyLogFileError):
        await analyze_service.accept(
            stream=None,
            vehicle_id_query=None,
            background_tasks=MagicMock(),
            session=MagicMock(),
            conn=MagicMock(),
            pool=MagicMock(),
            session_factory=MagicMock(),
            params=_make_params(),
            storage_dir=empty_log.parent,
            default_log_path=empty_log,
            max_upload_mb=10,
        )


@pytest.mark.anyio
async def test_accept_vehicle_id_query_passed_to_create_run(
    default_log: Path, mocker: MockerFixture
) -> None:
    run = _make_run(status=RunStatus.PENDING)
    mocker.patch("app.application.analyze_service._hash_file", return_value="abc123")
    mock_create = mocker.patch("app.infra.persistence.run_repository.create_run", return_value=run)
    mocker.patch("app.application.analyze_service.get_current_zone_hash", return_value="zh1")
    mocker.patch("app.application.analyze_service.asyncio.to_thread", side_effect=_fake_to_thread)

    await analyze_service.accept(
        stream=None,
        vehicle_id_query="V99",
        background_tasks=MagicMock(),
        session=MagicMock(),
        conn=MagicMock(),
        pool=MagicMock(),
        session_factory=MagicMock(),
        params=_make_params(),
        storage_dir=default_log.parent,
        default_log_path=default_log,
        max_upload_mb=10,
    )

    assert mock_create.call_args.kwargs["vehicle_id_default"] == "V99"


@pytest.mark.anyio
async def test_accept_no_vehicle_id_defaults_to_unknown(
    default_log: Path, mocker: MockerFixture
) -> None:
    run = _make_run(status=RunStatus.PENDING)
    mocker.patch("app.application.analyze_service._hash_file", return_value="abc123")
    mock_create = mocker.patch("app.infra.persistence.run_repository.create_run", return_value=run)
    mocker.patch("app.application.analyze_service.get_current_zone_hash", return_value="zh1")
    mocker.patch("app.application.analyze_service.asyncio.to_thread", side_effect=_fake_to_thread)

    await analyze_service.accept(
        stream=None,
        vehicle_id_query=None,
        background_tasks=MagicMock(),
        session=MagicMock(),
        conn=MagicMock(),
        pool=MagicMock(),
        session_factory=MagicMock(),
        params=_make_params(),
        storage_dir=default_log.parent,
        default_log_path=default_log,
        max_upload_mb=10,
    )

    assert mock_create.call_args.kwargs["vehicle_id_default"] == "UNKNOWN"


@pytest.mark.anyio
async def test_accept_stream_calls_save_upload_and_hash(
    default_log: Path, mocker: MockerFixture
) -> None:
    run = _make_run(status=RunStatus.PENDING)
    stream = MagicMock()
    mock_save = mocker.patch(
        "app.application.analyze_service.save_upload_and_hash",
        new=AsyncMock(return_value=(default_log, "deadbeef")),
    )
    mocker.patch("app.infra.persistence.run_repository.create_run", return_value=run)
    mocker.patch("app.application.analyze_service.get_current_zone_hash", return_value="zh1")
    mocker.patch("app.application.analyze_service.asyncio.to_thread", side_effect=_fake_to_thread)

    result = await analyze_service.accept(
        stream=stream,
        vehicle_id_query=None,
        background_tasks=MagicMock(),
        session=MagicMock(),
        conn=MagicMock(),
        pool=MagicMock(),
        session_factory=MagicMock(),
        params=_make_params(),
        storage_dir=default_log.parent,
        default_log_path=default_log,
        max_upload_mb=5,
    )

    mock_save.assert_called_once()
    assert mock_save.call_args.args[0] is stream
    assert mock_save.call_args.kwargs["size_limit"] == 5 * 1024 * 1024
    assert result.status == RunStatus.PENDING


def test_run_analysis_marks_failed_on_ingest_error(mocker: MockerFixture) -> None:
    exc = RuntimeError("disk full")
    mock_pool = MagicMock()
    mock_factory = MagicMock()
    mocker.patch("app.application.analyze_service._ingest", side_effect=exc)
    mock_set_status = mocker.patch("app.infra.persistence.run_repository.set_status")

    mock_err_session = MagicMock()
    mock_factory.return_value.__enter__.return_value = mock_err_session

    with pytest.raises(RuntimeError, match="disk full"):
        analyze_service.run_analysis(
            run_id=42,
            file_path=Path("/fake/path.json"),
            params=_make_params(),
            pool=mock_pool,
            session_factory=mock_factory,
        )

    mock_set_status.assert_called_once_with(
        mock_err_session,
        run_id=42,
        status=RunStatus.FAILED,
        error_message="disk full",
    )
    mock_err_session.commit.assert_called_once()


async def _fake_to_thread(func, *args, **kwargs):  # type: ignore[no-untyped-def]
    return func(*args, **kwargs)
