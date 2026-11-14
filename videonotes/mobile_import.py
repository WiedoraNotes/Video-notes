"""Bounded local portable file exchange for a future Android/iOS UI.

Imports and previews are read-only. Explicit exports create only new private
JSON files without changing project transcripts, edits or checkpoints.
Byte-range crash resume is not implemented.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from collections.abc import Callable

from .errors import VideoNotesError
from .mobile_contract import (
    _invalid_constant, _unique_keys,
    parse_portable_export, validate_portable_export,
)
from .stable_local_read import MAX_JSON_BYTES, read_stable_local_json as _read_stable_file


def import_portable_file(source: Path) -> dict:
    """Validate a stable local transcript without partially applying edits."""
    raw, source_sha256 = _read_stable_file(source)
    doc = parse_portable_export(raw)
    return {"document": doc, "source_sha256": source_sha256,
            "source_bytes": len(raw), "read_only": True}


def import_mobile_corrections_file(document: dict, source: Path) -> dict:
    """Preview an on-disk mobile/browser patch against a specific export.

    Fail the entire preview on a wrong project, stale source, duplicate IDs,
    malformed JSON, oversized data or an in-place file change. Never save
    project state. A deliberate desktop import is needed to apply corrections.
    """
    from .mobile_corrections import parse_mobile_corrections

    raw, source_sha256 = _read_stable_file(source)
    changes = parse_mobile_corrections(document, raw)
    return {"changes": changes, "source_sha256": source_sha256,
            "source_bytes": len(raw), "read_only": True}


def _publish_private_json(payload: bytes, destination: Path, *,
                          verify_source: Callable[[], bool] | None = None) -> dict:
    """Atomically create a *new* local JSON; never replace user files."""
    if not isinstance(payload, bytes) or len(payload) > MAX_JSON_BYTES:
        raise VideoNotesError("Plik eksportu przekracza 20 MiB.")
    target = Path(destination).expanduser().absolute()
    if target.suffix.lower() != ".json":
        raise VideoNotesError("Wybierz docelowy plik poprawek .json.")
    parent = target.parent
    if any(folder.is_symlink() or getattr(folder, "is_junction", lambda: False)()
           for folder in (parent, *parent.parents)):
        raise VideoNotesError("Katalog docelowy nie może być dowiązaniem.")
    if not parent.is_dir():
        raise VideoNotesError("Katalog docelowy poprawek musi już istnieć.")
    if target.exists() or target.is_symlink():
        raise VideoNotesError("Plik poprawek już istnieje; nie nadpisuję go.")
    try:
        with tempfile.TemporaryDirectory(prefix=".vn-mobile-patch-", dir=parent) as temp:
            stage = Path(temp) / "document.json"
            with stage.open("xb") as writer:
                writer.write(payload)
                writer.flush()
                os.fsync(writer.fileno())
            # Re-read the original file after staging to prevent a draft from
            # silently binding to a transcript changed while writing.
            # This is best effort against external writers, not an OS lock.
            if verify_source is not None and verify_source() is not True:
                raise VideoNotesError("Transkrypcja źródłowa zmieniła się; nie zapisano pliku.")
            try:
                os.link(stage, target)
            except FileExistsError as error:
                raise VideoNotesError("Plik poprawek powstał równolegle; nie nadpisuję go.") from error
            except OSError as error:
                raise VideoNotesError(
                    "Nośnik nie pozwala bezpiecznie opublikować nowej paczki poprawek."
                ) from error
    except OSError as error:
        raise VideoNotesError("Nie można przygotować lokalnego pliku poprawek.") from error
    return {"patch_sha256": hashlib.sha256(payload).hexdigest(),
            "patch_bytes": len(payload), "applied": False}


def export_mobile_corrections_file(
    document: dict, edits: dict[str, str], destination: Path, *,
    verify_source: Callable[[], bool] | None = None,
) -> dict:
    """Publish validated mobile/browser corrections without overwriting."""
    from .mobile_corrections import render_mobile_corrections

    payload = render_mobile_corrections(document, edits)
    return _publish_private_json(payload, destination, verify_source=verify_source)


MOBILE_EDIT_DRAFT_SCHEMA = "videonotes-mobile-edit-draft-v2"
_SHA256 = re.compile("[a-f0-9]{64}", re.ASCII)


def export_mobile_edit_draft_file(
    document: dict, source_sha256: str, destination: Path, *,
    verify_source: Callable[[], bool] | None = None,
) -> dict:
    """Create an editable template bound to exact transcript export bytes.

    It contains no ASR text or edits; private project ID and SHA stay on disk.
    Existing paths are never overwritten and no project data are changed.
    """
    canonical = validate_portable_export(document)
    if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
        raise VideoNotesError("Nieprawidłowy SHA-256 źródłowego eksportu.")
    payload = (json.dumps({
        "schema": MOBILE_EDIT_DRAFT_SCHEMA,
        "project_id": canonical["project_id"],
        "source_sha256": source_sha256,
        "edits": {},
    }, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    report = _publish_private_json(payload, destination, verify_source=verify_source)
    return {"draft_sha256": report["patch_sha256"],
            "draft_bytes": report["patch_bytes"], "applied": False}


def read_mobile_edit_draft_file(document: dict, source: Path, *, source_sha256: str) -> dict[str, str]:
    """Read explicit, private edits for a local offline patch export.

    This input is NOT a corrections patch. It binds edited segment IDs to a
    particular source project AND exact export SHA-256, and never uses CLI arguments for private text.
    It cannot update the raw ASR or a desktop project by itself.
    """
    canonical = validate_portable_export(document)
    if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
        raise VideoNotesError("Nieprawidłowy SHA-256 źródłowego eksportu.")
    raw, _ = _read_stable_file(source)
    try:
        draft = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys,
                           parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise VideoNotesError("Niepoprawny JSON lokalnego szkicu poprawek.") from error
    if (not isinstance(draft, dict)
            or set(draft) != {"schema", "project_id", "source_sha256", "edits"}
            or draft["schema"] != MOBILE_EDIT_DRAFT_SCHEMA
            or draft["project_id"] != canonical["project_id"]
            or draft["source_sha256"] != source_sha256
            or not isinstance(draft["edits"], dict)):
        raise VideoNotesError("Nieprawidłowa struktura lub projekt lokalnych poprawek.")
    # render_mobile_corrections validates every ID/text before writing a patch.
    from .mobile_corrections import render_mobile_corrections
    render_mobile_corrections(canonical, draft["edits"])
    return dict(draft["edits"])
