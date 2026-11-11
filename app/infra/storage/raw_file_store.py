import asyncio
import hashlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

from app.domain.exceptions import EmptyLogFileError, PayloadTooLargeError


def _write_and_hash(f: BinaryIO, hasher: "hashlib._Hash", chunk: bytes) -> None:
    hasher.update(chunk)
    f.write(chunk)


async def save_upload_and_hash(
    stream: AsyncIterator[bytes],
    storage_dir: Path,
    *,
    size_limit: int,
) -> tuple[Path, str]:
    hasher = hashlib.sha256()
    fd, tmp_name = tempfile.mkstemp(dir=storage_dir)
    tmp_path = Path(tmp_name)
    total = 0

    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in stream:
                total += len(chunk)
                if total > size_limit:
                    raise PayloadTooLargeError(size_limit // (1024 * 1024))
                await asyncio.to_thread(_write_and_hash, f, hasher, chunk)

        if total == 0:
            raise EmptyLogFileError()

        sha256 = hasher.hexdigest()
        dest = storage_dir / f"{sha256}.json"
        tmp_path.replace(dest)
        return dest, sha256
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
