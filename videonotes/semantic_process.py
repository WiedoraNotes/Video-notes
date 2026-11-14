"""Bounded, private local llama.cpp output pipe shared by normal and metrics runs.

No shell, network, model download or public model/stdout logs. Every child is
started in a new process session/group for controlled cleanup on failure.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable
from typing import BinaryIO

from .asr_lab import _stop_process_tree
from .errors import VideoNotesError

MAX_REPLY_BYTES = 128 * 1024
READ_CHUNK = 8192


def run_bounded_llama(
    command: list[str], *, stdin=subprocess.DEVNULL, stdout: BinaryIO,
    stderr=subprocess.DEVNULL, shell: bool = False, timeout: float = 240,
    check: bool = False,
    observer: Callable[[subprocess.Popen], None] | None = None,
) -> subprocess.CompletedProcess:
    """Drain up to MAX_REPLY_BYTES while a watchdog enforces wall-clock time.

    Reading the child through a pipe prevents an untrusted local model from
    filling an unlimited response file before the existing JSON read limit.
    An optional observer samples the *same* real process for private metrics.
    """
    if (shell or check or stdin != subprocess.DEVNULL
            or stderr != subprocess.DEVNULL or not hasattr(stdout, "write")
            or isinstance(timeout, bool) or timeout <= 0):
        raise VideoNotesError("Niebezpieczne ustawienia procesu lokalnego modelu.")
    launch = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
              if os.name == "nt" else {"start_new_session": True})
    try:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                shell=False, **launch)
    except OSError as error:
        raise VideoNotesError("Nie można uruchomić lokalnego silnika GGUF.") from error
    finished = threading.Event()
    too_large = threading.Event()
    reader_errors: list[Exception] = []

    def _drain() -> None:
        total = 0
        try:
            assert proc.stdout is not None
            while True:
                part = proc.stdout.read(min(READ_CHUNK, MAX_REPLY_BYTES + 1 - total))
                if not part:
                    break
                total += len(part)
                if total > MAX_REPLY_BYTES:
                    too_large.set()
                    break
                stdout.write(part)
            if not too_large.is_set():
                stdout.flush()
        except (OSError, ValueError) as error:
            reader_errors.append(error)
        finally:
            finished.set()

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    started = time.monotonic()
    try:
        while not finished.wait(0.025):
            if too_large.is_set():
                raise VideoNotesError("Lokalny model zwrócił nadmierną odpowiedź. Niczego nie zapisano.")
            if time.monotonic() - started > timeout:
                raise subprocess.TimeoutExpired(command, timeout)
            if observer is not None:
                observer(proc)
        if too_large.is_set():
            raise VideoNotesError("Lokalny model zwrócił nadmierną odpowiedź. Niczego nie zapisano.")
        if reader_errors:
            raise VideoNotesError("Nie udało się bezpiecznie odczytać odpowiedzi lokalnego modelu.")
        remaining = max(0.001, timeout - (time.monotonic() - started))
        returncode = proc.wait(timeout=remaining)
        return subprocess.CompletedProcess(command, returncode)
    except (VideoNotesError, subprocess.TimeoutExpired):
        _stop_process_tree(proc)
        raise
    except (OSError, ValueError) as error:
        _stop_process_tree(proc)
        raise VideoNotesError("Proces lokalnego modelu zakończył się nieprawidłowo.") from error
    finally:
        if proc.poll() is None:
            _stop_process_tree(proc)
        if proc.stdout is not None:
            proc.stdout.close()
        reader.join(timeout=1)
