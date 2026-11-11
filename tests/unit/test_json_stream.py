import json
from pathlib import Path

import pytest

from app.domain.exceptions import InvalidLogFormatError
from app.infra.parsing.json_stream import iter_chunks


def _write(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "log.json"
    p.write_text(json.dumps(data))
    return p


def test_all_items_returned_no_skip(tmp_path: Path) -> None:
    records = [{"id": i} for i in range(5)]
    path = _write(tmp_path, records)

    chunks, rejecteds = zip(*iter_chunks(path, chunk_size=10), strict=False)
    assert list(chunks[0]) == records
    assert list(rejecteds[0]) == []


def test_seek_does_not_drop_first_item(tmp_path: Path) -> None:
    records = [{"id": 0}, {"id": 1}]
    path = _write(tmp_path, records)

    result = []
    for chunk, _ in iter_chunks(path, chunk_size=10):
        result.extend(chunk)

    assert result[0] == {"id": 0}


def test_chunk_size_splits_correctly(tmp_path: Path) -> None:
    records = [{"i": i} for i in range(5)]
    path = _write(tmp_path, records)

    chunks = [chunk for chunk, _ in iter_chunks(path, chunk_size=2)]
    assert [len(c) for c in chunks] == [2, 2, 1]


def test_non_dict_item_goes_to_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"ok": 1}, "bad", {"ok": 2}])

    chunks = []
    rejecteds = []
    for chunk, rejected in iter_chunks(path, chunk_size=10):
        chunks.extend(chunk)
        rejecteds.extend(rejected)

    assert chunks == [{"ok": 1}, {"ok": 2}]
    assert rejecteds == [(1, "bad")]


def test_skip_preserves_original_index_in_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"a": 0}, "bad_at_1", {"a": 2}])

    rejecteds = []
    for _, rejected in iter_chunks(path, chunk_size=10, skip=1):
        rejecteds.extend(rejected)

    assert rejecteds == [(1, "bad_at_1")]


def test_skip_excludes_leading_items(tmp_path: Path) -> None:
    records = [{"i": i} for i in range(4)]
    path = _write(tmp_path, records)

    result = []
    for chunk, _ in iter_chunks(path, chunk_size=10, skip=2):
        result.extend(chunk)

    assert result == [{"i": 2}, {"i": 3}]


def test_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_bytes(b"")

    with pytest.raises(InvalidLogFormatError, match="빈 파일"):
        list(iter_chunks(path, chunk_size=10))


def test_non_array_top_level_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, {"key": "value"})

    with pytest.raises(InvalidLogFormatError, match="배열"):
        list(iter_chunks(path, chunk_size=10))


def test_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(b"[{bad json")

    with pytest.raises(InvalidLogFormatError):
        list(iter_chunks(path, chunk_size=10))
