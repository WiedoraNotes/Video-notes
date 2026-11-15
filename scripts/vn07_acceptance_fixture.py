"""Generate synthetic, private-by-default VN-07 physical browser acceptance inputs.

No recordings, network, private user data or real hardware are involved.
The output directory must be NEW, so existing files are never overwritten.
These fixtures only prepare manual testing; they cannot grant WEB-01/02 PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import wave
import os
import sys
from pathlib import Path

# Support both `python -m scripts.vn07_acceptance_fixture` and direct Windows use.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from videonotes.errors import VideoNotesError
from videonotes.mobile_contract import parse_portable_export
from videonotes.mobile_corrections import parse_mobile_corrections, render_mobile_corrections


def document(project_id: str, count: int) -> dict:
    return {
        "schema": "videonotes-export-v1",
        "project_id": project_id,
        "language": "pl",
        "complete": True,
        "segments": [
            {
                "id": f"seg-{i:05d}",
                "start_ms": i * 1500,
                "end_ms": i * 1500 + 1000,
                "text": f"Syntetyczna wypowiedź {i}: Zażółć gęślą jaźń, znacznik-{i}",
            }
            for i in range(count)
        ],
    }


def encode_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def synthetic_files() -> dict[str, bytes]:
    small = document("vn07-synthetic-small", 3)
    large = document("vn07-synthetic-50000", 50000)
    small_payload = encode_json(small)
    large_payload = encode_json(large)
    patch = render_mobile_corrections(small, {"seg-00001": "Zmieniony tekst wyłącznie do testu."})
    foreign = json.loads(patch)
    foreign["project_id"] = "vn07-synthetic-foreign"
    valid_text = json.dumps(small["segments"][0]["text"], ensure_ascii=False)
    malformed = small_payload.decode("utf-8").replace(
        '"text": ' + valid_text,
        '"text": "Nieuprawniona podmiana", "text": ' + valid_text,
        1,
    ).encode("utf-8")
    if malformed == small_payload:
        raise RuntimeError("Cannot construct duplicate-key test fixture")
    audio = io.BytesIO()
    with wave.open(audio, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(1)
        output.setframerate(8000)
        output.writeframes(bytes([128]) * (8000 * 4))
    files = {
        "vn07-silent-four-seconds.wav": audio.getvalue(),
        "vn07-small.json": small_payload,
        "vn07-large-50000.json": large_payload,
        "vn07-corrections.json": patch,
        "vn07-foreign-corrections.json": encode_json(foreign),
        "vn07-duplicate-key.json": malformed,
        "vn07-deeply-nested.json": ("[" * 15000 + "0" + "]" * 15000).encode("utf-8"),
    }
    if len(large_payload) > 20 * 1024 * 1024:
        raise RuntimeError("50k fixture exceeds browser input limit")
    # Self-check in the same portable Python contracts consumed by desktop/mobile.
    if len(parse_portable_export(small_payload)["segments"]) != 3:
        raise RuntimeError("Invalid synthetic small export")
    if len(parse_portable_export(large_payload)["segments"]) != 50000:
        raise RuntimeError("Invalid synthetic large export")
    if parse_mobile_corrections(small, patch) != {"seg-00001": "Zmieniony tekst wyłącznie do testu."}:
        raise RuntimeError("Invalid corrections fixture")
    return files


def generate(output: Path) -> dict:
    output = Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise VideoNotesError("Katalog testowy już istnieje; nie nadpisuję danych.")
    parent = output.parent
    if not parent.is_dir() or any(path.is_symlink() or getattr(path, "is_junction", lambda: False)()
                                   for path in (parent, *parent.parents)):
        raise VideoNotesError("Wybierz istniejący zwykły katalog nadrzędny bez dowiązań.")
    files = synthetic_files()
    # O_EXCL/O_CREAT for the entire new folder makes this idempotent and
    # independent of any existing real KWN project.
    try:
        output.mkdir(mode=0o700)
    except FileExistsError as error:
        raise VideoNotesError("Katalog testowy powstał równolegle; niczego nie nadpisano.") from error
    except OSError as error:
        raise VideoNotesError("Nie można stworzyć katalogu testowego.") from error
    report = {"schema": "videonotes-vn07-synthetic-fixtures-v1", "synthetic_only": True,
              "human_acceptance": False, "files": {}}
    for name, payload in files.items():
        target = output / name
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        report["files"][name] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    manifest = encode_json(report)
    fd = os.open(output / "manifest.json",
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(manifest)
        stream.flush()
        os.fsync(stream.fileno())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate offline, synthetic VN-07 browser acceptance fixtures")
    parser.add_argument("--output", required=True, type=Path,
                        help="NEW local directory; never points to an existing KWN project")
    args = parser.parse_args()
    try:
        report = generate(args.output)
    except (VideoNotesError, OSError) as error:
        # Don't expose the user-supplied path, private contents or traceback.
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
