from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from app.application import recovery
from app.domain.enums import RunStatus
from app.domain.params import AnalysisParams


def _make_run(*, run_id: int, status: RunStatus, file_path: str | None) -> MagicMock:
    run = MagicMock()
    run.id = run_id
    run.status = status
    run.file_path = file_path
    return run


@pytest.fixture()
def existing_file(tmp_path: Path) -> Path:
    p = tmp_path / "run.json"
    p.write_text("[]")
    return p


def test_recover_requeues_incomplete_runs(existing_file: Path, mocker: MockerFixture) -> None:
    runs = [
        _make_run(run_id=1, status=RunStatus.PENDING, file_path=str(existing_file)),
        _make_run(run_id=2, status=RunStatus.INGESTING, file_path=str(existing_file)),
    ]
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__.return_value = MagicMock()
    mocker.patch("app.infra.persistence.run_repository.claim_incomplete_runs", return_value=runs)
    bt = MagicMock()

    requeued = recovery.recover_incomplete_runs(
        bt,
        params=AnalysisParams(),
        session_factory=mock_factory,
        pool=MagicMock(),
        claim_limit=100,
    )

    assert requeued == 2
    assert bt.add_task.call_count == 2


@pytest.mark.parametrize(
    "file_path",
    [
        pytest.param(None, id="no_file_path"),
        pytest.param("/nonexistent/path.json", id="missing_file"),
    ],
)
def test_recover_skips_run_when_file_unavailable(
    file_path: str | None, mocker: MockerFixture
) -> None:
    runs = [_make_run(run_id=3, status=RunStatus.PENDING, file_path=file_path)]
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__.return_value = MagicMock()
    mocker.patch("app.infra.persistence.run_repository.claim_incomplete_runs", return_value=runs)
    bt = MagicMock()

    requeued = recovery.recover_incomplete_runs(
        bt,
        params=AnalysisParams(),
        session_factory=mock_factory,
        pool=MagicMock(),
        claim_limit=100,
    )

    assert requeued == 0
    bt.add_task.assert_not_called()


def test_recover_counts_only_requeued_not_skipped(
    existing_file: Path, mocker: MockerFixture
) -> None:
    runs = [
        _make_run(run_id=1, status=RunStatus.PENDING, file_path=str(existing_file)),
        _make_run(run_id=2, status=RunStatus.INGESTING, file_path="/nonexistent/path.json"),
    ]
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__.return_value = MagicMock()
    mocker.patch("app.infra.persistence.run_repository.claim_incomplete_runs", return_value=runs)
    bt = MagicMock()

    requeued = recovery.recover_incomplete_runs(
        bt,
        params=AnalysisParams(),
        session_factory=mock_factory,
        pool=MagicMock(),
        claim_limit=100,
    )

    assert requeued == 1
    assert bt.add_task.call_count == 1
