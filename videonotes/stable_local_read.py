"""Shared stable, bounded local JSON file reader for desktop, web and mobile.

This does not parse JSON or modify a file. It only checks bytes and identity.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from .errors import VideoNotesError

MAX_JSON_BYTES = 20 * 1024 * 1024
READ_SIZE = 64 * 1024


def read_stable_local_json(source: Path) -> tuple[bytes, str]:
    """Read at most 20 MiB from one regular file and reject concurrent edits.

    Re-read the same file descriptor using SHA-256 to detect same-size edits
    on coarse-timestamp Windows filesystems. Verify original path identity.
    The digest describes exactly the bytes returned for later parsing.
    """
    path = Path(source).expanduser()
    if path.is_symlink():
        raise VideoNotesError("Import nie pozwala na dowiązania symboliczne.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_JSON_BYTES:
                raise VideoNotesError("Wymagany jest zwykły plik JSON do 20 MiB.")
            contents = bytearray()
            digest = hashlib.sha256()
            while True:
                block = os.read(fd, min(READ_SIZE, MAX_JSON_BYTES + 1 - len(contents)))
                if not block:
                    break
                contents.extend(block)
                digest.update(block)
                if len(contents) > MAX_JSON_BYTES:
                    raise VideoNotesError("Eksport przekracza limit 20 MiB.")
            # Some Windows filesystems coarsen timestamps. Read the bounded
            # descriptor a second time and compare bytes via SHA-256 even when
            # the file metadata appears unchanged after an in-place rewrite.
            os.lseek(fd, 0, os.SEEK_SET)
            verify = hashlib.sha256()
            verified_bytes = 0
            while True:
                block = os.read(fd, min(READ_SIZE, MAX_JSON_BYTES + 1 - verified_bytes))
                if not block:
                    break
                verify.update(block)
                verified_bytes += len(block)
                if verified_bytes > MAX_JSON_BYTES:
                    raise VideoNotesError("Eksport przekracza limit 20 MiB.")
            if verified_bytes != len(contents) or verify.digest() != digest.digest():
                raise VideoNotesError("Zawartość pliku zmieniła się podczas importu.")
            after = os.fstat(fd)
            if (before.st_dev != after.st_dev or
                    before.st_ino != after.st_ino or
                    before.st_size != after.st_size or
                    before.st_mtime_ns != after.st_mtime_ns or
                    before.st_ctime_ns != after.st_ctime_ns or
                    len(contents) != after.st_size):
                raise VideoNotesError("Plik zmienił się w trakcie importu.")
        finally:
            os.close(fd)
        visible = path.lstat()
    except OSError as error:
        raise VideoNotesError("Nie można bezpiecznie odczytać eksportu.") from error
    if (not stat.S_ISREG(visible.st_mode)
            or visible.st_dev != after.st_dev or visible.st_ino != after.st_ino
            or visible.st_size != after.st_size
            or visible.st_mtime_ns != after.st_mtime_ns):
        raise VideoNotesError("Źródłowy plik importu został podmieniony.")
    return bytes(contents), digest.hexdigest()
