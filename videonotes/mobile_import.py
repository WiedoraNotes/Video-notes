"""Read-only, bounded local file adapter for a future Android/iOS UI.

On interrupted import the caller retries the file selection. Never writes
transcripts, edits or checkpoints; byte-range crash resume is not implemented.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .errors import VideoNotesError
from .mobile_contract import (
    MAX_JSON_BYTES, _invalid_constant, _unique_keys,
    parse_portable_export, validate_portable_export,
)


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


def export_mobile_corrections_file(document: dict, edits: dict[str, str],
                                   destination: Path) -> dict:
    """Publish a local corrections JSON without replacing any existing file.

    Stage and fsync under a private temporary directory on the same volume,
    then create the final path by hard link (atomic no-clobber). If the
    filesystem cannot create a hard link, refuse rather than leave an
    incomplete/partially visible patch. No project data is applied or uploaded.
    """
    from .mobile_corrections import render_mobile_corrections

    payload = render_mobile_corrections(document, edits)
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
            stage = Path(temp) / "corrections.json"
            with stage.open("xb") as writer:
                writer.write(payload)
                writer.flush()
                os.fsync(writer.fileno())
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


MOBILE_EDIT_DRAFT_SCHEMA = "videonotes-mobile-edit-draft-v1"


def read_mobile_edit_draft_file(document: dict, source: Path) -> dict[str, str]:
    """Read explicit, private edits for a local offline patch export.

    This input is NOT a corrections patch. It binds edited segment IDs to a
    particular source project, and never uses CLI arguments for private text.
    It cannot update the raw ASR or a desktop project by itself.
    """
    canonical = validate_portable_export(document)
    raw, _ = _read_stable_file(source)
    try:
        draft = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys,
                           parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise VideoNotesError("Niepoprawny JSON lokalnego szkicu poprawek.") from error
    if (not isinstance(draft, dict)
            or set(draft) != {"schema", "project_id", "edits"}
            or draft["schema"] != MOBILE_EDIT_DRAFT_SCHEMA
            or draft["project_id"] != canonical["project_id"]
            or not isinstance(draft["edits"], dict)):
        raise VideoNotesError("Nieprawidłowa struktura lub projekt lokalnych poprawek.")
    # render_mobile_corrections validates every ID/text before writing a patch.
    from .mobile_corrections import render_mobile_corrections
    render_mobile_corrections(canonical, draft["edits"])
    return dict(draft["edits"])
