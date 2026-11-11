from collections.abc import Iterator
from pathlib import Path
from typing import Final

import ijson  # type: ignore[import-untyped]

from app.domain.exceptions import InvalidLogFormatError

_HEADER_READ_SIZE: Final = 4096


def iter_chunks(
    path: Path,
    chunk_size: int,
    skip: int = 0,
) -> Iterator[tuple[list[dict[str, object]], list[tuple[int, object]]]]:
    with path.open("rb") as f:
        raw = f.read(_HEADER_READ_SIZE)
        first = raw.lstrip()
        if not first:
            raise InvalidLogFormatError("빈 파일입니다")
        if first[0:1] != b"[":
            raise InvalidLogFormatError("최상위가 배열이 아닙니다")
        f.seek(0)

        try:
            chunk: list[dict[str, object]] = []
            rejected: list[tuple[int, object]] = []

            for index, item in enumerate(ijson.items(f, "item")):
                if index < skip:
                    continue
                if not isinstance(item, dict):
                    rejected.append((index, item))
                    continue
                chunk.append(item)
                if len(chunk) >= chunk_size:
                    yield chunk, rejected
                    chunk = []
                    rejected = []

            if chunk or rejected:
                yield chunk, rejected

        except ijson.JSONError as e:
            raise InvalidLogFormatError(str(e)) from e
