"""Offline CLI roundtrip for the optional mobile interchange boundary.

Synthetic fixtures only, no Android/iOS devices, microphones or human review.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from videonotes.cli import main
from videonotes.mobile_import import MOBILE_EDIT_DRAFT_SCHEMA


class MobileCliTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source = root / "transcript.json"
        self.edits = root / "edits.json"
        self.patch = root / "corrections.json"
        self.document = {
            "schema": "videonotes-export-v1", "project_id": "PRIVATE_PROJECT_71",
            "language": "pl", "complete": False,
            "segments": [
                {"id": "s0", "start_ms": 0, "end_ms": 1200,
                 "text": "PRIVATE_SOURCE_71 Zażółć"},
                {"id": "s1", "start_ms": 1300, "end_ms": 2200, "text": "Druga wypowiedź"},
            ],
        }
        self.source.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")
        self.draft = {
            "schema": MOBILE_EDIT_DRAFT_SCHEMA,
            "project_id": self.document["project_id"],
            "edits": {"s0": "PRIVATE_AFTER_72 nowa treść 😀"},
        }
        self.write_draft()

    def write_draft(self):
        self.edits.write_text(json.dumps(self.draft, ensure_ascii=False), encoding="utf-8")

    def execute(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main(list(args))
        return status, out.getvalue(), err.getvalue()

    def assert_private_output(self, output):
        for private in ("PRIVATE_PROJECT_71", "PRIVATE_SOURCE_71", "PRIVATE_AFTER_72"):
            self.assertNotIn(private, output)

    def test_complete_cli_roundtrip_no_private_stdout_or_asr_writes(self):
        initial_source = self.source.read_bytes()
        initial_edits = self.edits.read_bytes()
        status, output, error = self.execute("mobile-import-check", str(self.source))
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output)["segments"], 2)
        self.assert_private_output(output)
        status, output, error = self.execute(
            "mobile-patch-create", "--source", str(self.source),
            "--edits", str(self.edits), "--output", str(self.patch),
        )
        self.assertEqual(status, 0, error)
        published = json.loads(output)
        self.assertEqual(published["submitted_edits"], 1)
        self.assertFalse(published["applied"])
        self.assert_private_output(output)
        patch = json.loads(self.patch.read_text(encoding="utf-8"))
        self.assertEqual(patch["project_id"], self.document["project_id"])
        self.assertEqual(patch["changes"][0]["after"], self.draft["edits"]["s0"])
        status, output, error = self.execute(
            "mobile-patch-check", "--source", str(self.source), "--file", str(self.patch),
        )
        self.assertEqual(status, 0, error)
        verified = json.loads(output)
        self.assertEqual(verified["changes"], 1)
        self.assertEqual(verified["patch_sha256"], published["patch_sha256"])
        self.assertTrue(verified["read_only"])
        self.assert_private_output(output)
        self.assertEqual(self.source.read_bytes(), initial_source)
        self.assertEqual(self.edits.read_bytes(), initial_edits)

    def test_wrong_project_and_unknown_segment_are_refused_without_writes(self):
        for edits in (
            {**self.draft, "project_id": "OTHER"},
            {**self.draft, "edits": {"foreign": "PRIVATE_AFTER_72"}},
            {**self.draft, "edits": {"s0": None}},
        ):
            with self.subTest(edits=edits):
                self.edits.write_text(json.dumps(edits), encoding="utf-8")
                status, output, error = self.execute(
                    "mobile-patch-create", "--source", str(self.source),
                    "--edits", str(self.edits), "--output", str(self.patch),
                )
                self.assertEqual(status, 2)
                self.assertFalse(output)
                self.assertNotIn("Traceback", error)
                self.assert_private_output(error)
                self.assertFalse(self.patch.exists())

    def test_duplicate_draft_fields_and_nonstandard_json_fail_closed(self):
        for invalid in (
            b'{"schema":"videonotes-mobile-edit-draft-v1","schema":"other","project_id":"PRIVATE_PROJECT_71","edits":{}}',
            b'{"schema":"videonotes-mobile-edit-draft-v1","project_id":"PRIVATE_PROJECT_71","edits":{"s0":"ok","s0":"bad"}}',
            b'{"schema":"videonotes-mobile-edit-draft-v1","project_id":"PRIVATE_PROJECT_71","edits":{"s0":NaN}}',
            b"\xff",
        ):
            with self.subTest(payload=invalid[:32]):
                self.edits.write_bytes(invalid)
                status, output, error = self.execute(
                    "mobile-patch-create", "--source", str(self.source),
                    "--edits", str(self.edits), "--output", str(self.patch),
                )
                self.assertEqual(status, 2)
                self.assertFalse(output)
                self.assertFalse(self.patch.exists())
                self.assert_private_output(error)

    def test_existing_export_is_preserved_and_stale_patch_rejected(self):
        self.patch.write_bytes(b"KEEP_EXISTING")
        status, output, error = self.execute(
            "mobile-patch-create", "--source", str(self.source),
            "--edits", str(self.edits), "--output", str(self.patch),
        )
        self.assertEqual(status, 2)
        self.assertFalse(output)
        self.assertEqual(self.patch.read_bytes(), b"KEEP_EXISTING")
        self.patch.unlink()
        status, _, error = self.execute(
            "mobile-patch-create", "--source", str(self.source),
            "--edits", str(self.edits), "--output", str(self.patch),
        )
        self.assertEqual(status, 0, error)
        self.document["segments"][0]["text"] = "changed source"
        self.source.write_text(json.dumps(self.document), encoding="utf-8")
        status, output, error = self.execute(
            "mobile-patch-check", "--source", str(self.source), "--file", str(self.patch),
        )
        self.assertEqual(status, 2)
        self.assertFalse(output)
        self.assert_private_output(error)

    def test_empty_edits_and_missing_input_handled_without_cloud(self):
        self.draft["edits"] = {}
        self.write_draft()
        status, _, error = self.execute(
            "mobile-patch-create", "--source", str(self.source),
            "--edits", str(self.edits), "--output", str(self.patch),
        )
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(self.patch.read_text())["changes"], [])
        self.source.unlink()
        status, output, error = self.execute("mobile-import-check", str(self.source))
        self.assertEqual(status, 2)
        self.assertFalse(output)
        self.assertNotIn("Traceback", error)


if __name__ == "__main__":
    unittest.main()
