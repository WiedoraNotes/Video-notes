"""Full offline desktop-export/mobile-draft/browser-patch/desktop-preview flow.

All inputs are synthetic local fixture files; this is NOT a device acceptance.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_contracts import demo_project, demo_transcript
from videonotes.cli import main
from videonotes.errors import VideoNotesError
from videonotes.exports import edit_segment, export_project
from videonotes.handoff_audit import audit_offline_handoff
from videonotes.mobile_import import (
    export_mobile_corrections_file, export_mobile_edit_draft_file,
    import_portable_file, read_mobile_edit_draft_file,
)
from videonotes.storage import read_project, save_json
from videonotes.web_corrections import import_web_corrections


class OfflineHandoffAuditTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        save_json(self.project / "project.json", demo_project())
        save_json(self.project / "transcript.json", demo_transcript())
        export_project(self.project)
        self.source = self.project / "exports" / "transcript.json"
        self.draft = self.root / "draft.json"
        self.patch = self.root / "corrections.json"
        self.sid = "c0000000-s00000"
        self.private_edit = "PRIVATE_NEW_TEXT Zażółć 😀"
        self.initial_raw = (self.project / "transcript.json").read_bytes()
        self.initial_source = self.source.read_bytes()

    def make_patch(self):
        source = import_portable_file(self.source)
        export_mobile_edit_draft_file(source["document"], source["source_sha256"], self.draft)
        edits = json.loads(self.draft.read_text("utf-8"))
        edits["edits"][self.sid] = self.private_edit
        self.draft.write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
        validated = read_mobile_edit_draft_file(
            source["document"], self.draft, source_sha256=source["source_sha256"]
        )
        export_mobile_corrections_file(source["document"], validated, self.patch)

    def test_read_only_audit_and_full_explicit_desktop_apply(self):
        self.make_patch()
        initial_patch = self.patch.read_bytes()
        report = audit_offline_handoff(self.project, self.source, self.patch)
        self.assertTrue(report["read_only"])
        self.assertTrue(report["source_matches_desktop"])
        self.assertTrue(report["requires_manual_acceptance"])
        self.assertEqual(report["patch"], "preview_only")
        self.assertEqual(report["patch_changed_segments"], 1)
        self.assertEqual(report["desktop_changed_segments"], 1)
        self.assertEqual(report["segments"], 2)
        self.assertNotIn("project_id", report)
        self.assertFalse((self.project / "edits.json").exists())
        self.assertEqual(self.initial_raw, (self.project / "transcript.json").read_bytes())
        self.assertEqual(initial_patch, self.patch.read_bytes())
        self.assertEqual(self.initial_source, self.source.read_bytes())
        applied = import_web_corrections(self.project, self.patch, apply=True)
        self.assertEqual(applied["changed"], 1)
        self.assertEqual(read_project(self.project)[2]["edits"][self.sid], self.private_edit)
        self.assertEqual(self.initial_raw, (self.project / "transcript.json").read_bytes())

    def test_cli_output_contains_only_safe_counts_and_hashes(self):
        self.make_patch()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = main(["handoff-audit", str(self.project), "--source", str(self.source),
                           "--patch", str(self.patch)])
        self.assertEqual(status, 0, stderr.getvalue())
        record = json.loads(stdout.getvalue())
        self.assertEqual(record["patch_changed_segments"], 1)
        for sensitive in (self.private_edit, "test-123", "Zażółć gęślą", str(self.project)):
            self.assertNotIn(sensitive, stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertFalse((self.project / "edits.json").exists())

    def test_source_only_preflight_has_no_patch_or_writes(self):
        report = audit_offline_handoff(self.project, self.source)
        self.assertEqual(report["patch"], "not_supplied")
        self.assertNotIn("patch_sha256", report)
        self.assertFalse((self.project / "edits.json").exists())
        self.assertEqual(self.source.read_bytes(), self.initial_source)

    def test_stale_export_refused_even_if_source_file_is_valid_json(self):
        self.make_patch()
        edit_segment(self.project, self.sid, "desktop changed after last export")
        before = (self.project / "edits.json").read_bytes()
        with self.assertRaisesRegex(VideoNotesError, "Eksport nie odpowiada"):
            audit_offline_handoff(self.project, self.source, self.patch)
        self.assertEqual((self.project / "edits.json").read_bytes(), before)
        self.assertEqual((self.project / "transcript.json").read_bytes(), self.initial_raw)

    def test_changed_patch_during_desktop_preview_aborts_final_audit(self):
        self.make_patch()
        from videonotes import handoff_audit as module
        original = module.import_web_corrections

        def mutate_after_preview(*args, **kwargs):
            report = original(*args, **kwargs)
            contents = self.patch.read_bytes()
            changed = contents.replace(b"PRIVATE_NEW_TEXT", b"PRIVATE_ALT_TEXT")
            self.assertEqual(len(contents), len(changed))
            self.patch.write_bytes(changed)
            return report

        with patch.object(module, "import_web_corrections", side_effect=mutate_after_preview):
            with self.assertRaisesRegex(VideoNotesError, "Paczka poprawek zmieniła"):
                audit_offline_handoff(self.project, self.source, self.patch)
        self.assertFalse((self.project / "edits.json").exists())
        self.assertEqual(self.initial_raw, (self.project / "transcript.json").read_bytes())

    def test_changed_desktop_project_during_audit_aborts(self):
        from videonotes import handoff_audit as module
        original = module.render_exports
        calls = 0

        def desktop_changes(folder):
            nonlocal calls
            calls += 1
            if calls == 2:
                edit_segment(self.project, self.sid, "another desktop editor")
            return original(folder)

        with patch.object(module, "render_exports", side_effect=desktop_changes):
            with self.assertRaisesRegex(VideoNotesError, "Źródło lub projekt zmieniły"):
                audit_offline_handoff(self.project, self.source)
        self.assertEqual(calls, 2)
        self.assertEqual(self.initial_raw, (self.project / "transcript.json").read_bytes())

    def test_invalid_patch_or_source_cannot_modify_raw_asr(self):
        self.make_patch()
        from videonotes import mobile_import
        self.patch.write_bytes(b'{"schema":"fake"}')
        with self.assertRaises(VideoNotesError):
            audit_offline_handoff(self.project, self.source, self.patch)
        self.assertEqual(self.initial_raw, (self.project / "transcript.json").read_bytes())
        self.assertFalse((self.project / "edits.json").exists())


if __name__ == "__main__":
    unittest.main()
