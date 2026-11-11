import asyncio
import hashlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO


def _write_and_hash(f: BinaryIO, hasher: "hashlib._Hash", chunk: bytes) -> None:
    hasher.update(chunk)
    f.write(chunk)


async def save_upload_and_hash(
    stream: AsyncIterator[bytes],
    storage_dir: Path,
) -> tuple[Path, str]:
    hasher = hashlib.sha256()
    fd, tmp_name = tempfile.mkstemp(dir=storage_dir)
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in stream:
                await asyncio.to_thread(_write_and_hash, f, hasher, chunk)

        sha256 = hasher.hexdigest()
        dest = storage_dir / f"{sha256}.json"
        tmp_path.replace(dest)
        return dest, sha256
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
