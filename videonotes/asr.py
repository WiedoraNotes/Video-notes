"""Optional local whisper.cpp adapter; no models or libraries auto-downloaded."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .contracts import MAX_TEXT_LENGTH, utf16_code_units, valid_unicode_text
from .errors import VideoNotesError
from .media import _run, executable
from .stable_local_read import MAX_ASR_JSON_BYTES, read_stable_local_json


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    """Do not let duplicate JSON keys silently replace Whisper results."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise VideoNotesError("Silnik ASR zwrócił powielone pola JSON.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise VideoNotesError("Silnik ASR zwrócił niedozwoloną wartość liczbową.")


def parse_whisper_output(payload: object, *, offset_ms: int, duration_ms: int) -> list[dict]:
    if (type(offset_ms) is not int or type(duration_ms) is not int
            or offset_ms < 0 or duration_ms <= 0
            or offset_ms + duration_ms > 24 * 3600 * 1000):
        raise VideoNotesError("Nieprawidłowy czas fragmentu ASR.")
    if not isinstance(payload, dict) or not isinstance(payload.get("transcription"), list):
        raise VideoNotesError("Silnik ASR zwrócił nieprawidłowy JSON.")
    if len(payload["transcription"]) > 100_000:
        raise VideoNotesError("Silnik ASR zwrócił za dużo segmentów.")
    segments = []
    seen: set[tuple[int, int, str]] = set()
    for entry in payload["transcription"]:
        if not isinstance(entry, dict):
            raise VideoNotesError("Nieprawidłowy segment ASR.")
        raw = entry.get("text")
        offsets = entry.get("offsets")
        if not isinstance(raw, str) or not isinstance(offsets, dict):
            raise VideoNotesError("Brakuje tekstu lub czasu w wyniku ASR.")
        text = raw.strip()
        if not text:
            continue  # Silent fragment: leave checkpoint and progress untouched.
        if not valid_unicode_text(text) or utf16_code_units(text) > MAX_TEXT_LENGTH:
            raise VideoNotesError("Silnik ASR zwrócił tekst poza limitem lub błędny Unicode.")
        start, end = offsets.get("from"), offsets.get("to")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start or end > duration_ms + 500:
            raise VideoNotesError("Silnik ASR zwrócił nieprawidłowy czas segmentu.")
        absolute_start = offset_ms + min(start, duration_ms)
        absolute_end = offset_ms + min(end, duration_ms)
        if absolute_start >= absolute_end:
            raise VideoNotesError("Segment ASR wychodzi poza granice nagrania.")
        # Only exact same text AND time is a duplicate. Repeated speech at
        # distinct timestamps is legitimate and must not disappear.
        key = (absolute_start, absolute_end, text)
        if key in seen:
            continue
        seen.add(key)
        segments.append({"start_ms": key[0], "end_ms": key[1], "text": key[2]})
    segments.sort(key=lambda s: (s["start_ms"], s["end_ms"]))
    return segments


class WhisperCpp:
    def __init__(self, executable_path: str, model: Path):
        self.executable_path = executable(executable_path)
        self.model = Path(model).expanduser().resolve()
        if not self.model.is_file() or self.model.stat().st_size == 0:
            raise VideoNotesError("Model Whisper nie istnieje lub jest pusty. Pobierz go ręcznie zgodnie z licencją.")

    def transcribe(self, wav: Path, *, language: str, offset_ms: int, duration_ms: int) -> list[dict]:
        if language not in {"pl", "en", "auto"}:
            raise VideoNotesError("Nieobsługiwany język ASR.")
        with tempfile.TemporaryDirectory(prefix="vn-asr-") as temp:
            output = str(Path(temp) / "result")
            _run([self.executable_path, "--model", str(self.model), "--file", str(wav), "--language", language,
                  "--output-json", "--output-file", output, "--no-prints", "--no-gpu"], timeout=7200)
            try:
                file = Path(output + ".json")
                if file.is_symlink() or not file.is_file():
                    raise VideoNotesError("Silnik ASR zwrócił niedozwolony plik JSON.")
                # Verify the same descriptor twice (SHA-256 and inode/mtime).
                # A second writer or a replaced output must not be checkpointed.
                raw, _digest = read_stable_local_json(file, max_bytes=MAX_ASR_JSON_BYTES)
                payload = json.loads(raw.decode("utf-8"),
                                     object_pairs_hook=_unique_json_object,
                                     parse_constant=_reject_json_constant)
            except (FileNotFoundError, OSError, UnicodeError, ValueError,
                    RecursionError, OverflowError) as error:
                # Never echo model output or machine-local paths in an error.
                raise VideoNotesError("Nie można odczytać wynikowego JSON silnika ASR.") from error
        return parse_whisper_output(payload, offset_ms=offset_ms, duration_ms=duration_ms)
