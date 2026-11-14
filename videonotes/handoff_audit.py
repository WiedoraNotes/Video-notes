"""Read-only end-to-end audit for offline desktop/browser/mobile handoff.

The caller supplies local files. Nothing is uploaded, downloaded or written.
Passing means only that the selected portable transcript and optional browser
patch were structurally compatible with the current desktop project at the
time of verification. It is NOT a final device, quality or human acceptance.
"""
from __future__ import annotations

from pathlib import Path

from .errors import VideoNotesError
from .exports import render_exports
from .mobile_contract import parse_portable_export
from .mobile_import import import_mobile_corrections_file, import_portable_file
from .web_corrections import import_web_corrections

SCHEMA = "videonotes-offline-handoff-audit-v1"


def audit_offline_handoff(project: Path, source_file: Path,
                          patch_file: Path | None = None) -> dict:
    """Check an export against current corrected project, then preview a patch.

    Cross-check BOTH portable parser and desktop patch preview to detect stale
    exports and source text conflicts. Never use apply=True. Only hashes/counts
    are returned to avoid printing transcript text or private project IDs.
    """
    project = Path(project)
    selected = import_portable_file(source_file)
    original = selected["document"]
    fresh = parse_portable_export(render_exports(project)["transcript.json"])
    if original != fresh:
        raise VideoNotesError(
            "Eksport nie odpowiada aktualnej transkrypcji projektu. "
            "Najpierw ponownie wyeksportuj projekt; niczego nie zmieniono."
        )
    report = {
        "schema": SCHEMA,
        "source_sha256": selected["source_sha256"],
        "source_bytes": selected["source_bytes"],
        "segments": len(original["segments"]),
        "complete": original["complete"],
        "source_matches_desktop": True,
        "patch": "not_supplied",
        "read_only": True,
        "requires_manual_acceptance": True,
    }
    if patch_file is not None:
        mobile = import_mobile_corrections_file(original, patch_file)
        desktop = import_web_corrections(project, patch_file, apply=False)
        if desktop["mode"] != "preview":
            raise VideoNotesError("Audyt nie pozwala na zastosowanie poprawek.")
        report.update({
            "patch": "preview_only",
            "patch_sha256": mobile["source_sha256"],
            "patch_bytes": mobile["source_bytes"],
            "patch_changed_segments": len(mobile["changes"]),
            "desktop_changed_segments": desktop["changed"],
            "desktop_unchanged_segments": desktop["unchanged"],
        })
        # The browser file can be concurrently overwritten after the first
        # independent preview. Never return a positive report for mixed inputs.
        later_patch = import_mobile_corrections_file(original, patch_file)
        if later_patch["source_sha256"] != mobile["source_sha256"]:
            raise VideoNotesError("Paczka poprawek zmieniła się podczas audytu.")
    later_source = import_portable_file(source_file)
    if (later_source["source_sha256"] != selected["source_sha256"]
            or parse_portable_export(render_exports(project)["transcript.json"]) != fresh):
        raise VideoNotesError("Źródło lub projekt zmieniły się podczas audytu.")
    return report
