"""Offline CLI roundtrip for the optional mobile interchange boundary.

Synthetic fixtures only, no Android/iOS devices, microphones or human review.
"""
from __future__ import annotations

import contextlib
import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
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
            b'{"schema":"videonotes-mobile-edit-draft-v2","schema":"other","project_id":"PRIVATE_PROJECT_71","edits":{}}',
            b'{"schema":"videonotes-mobile-edit-draft-v2","project_id":"PRIVATE_PROJECT_71","edits":{"s0":"ok","s0":"bad"}}',
            b'{"schema":"videonotes-mobile-edit-draft-v2","project_id":"PRIVATE_PROJECT_71","edits":{"s0":NaN}}',
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


    def test_template_creation_is_source_bound_and_never_overwrites(self):
        draft = self.source.parent / "created-draft.json"
        initial = self.source.read_bytes()
        status, out, err = self.execute(
            "mobile-draft-init", "--source", str(self.source), "--output", str(draft),
        )
        self.assertEqual(status, 0, err)
        self.assert_private_output(out)
        self.assertEqual(len(json.loads(out)["draft_sha256"]), 64)
        self.assertGreater(json.loads(out)["draft_bytes"], 0)
        template = json.loads(draft.read_text("utf-8"))
        self.assertEqual(template["schema"], MOBILE_EDIT_DRAFT_SCHEMA)
        self.assertEqual(template["project_id"], self.document["project_id"])
        self.assertEqual(template["source_sha256"], hashlib.sha256(initial).hexdigest())
        self.assertEqual(template["edits"], {})
        self.assertNotIn("PRIVATE_SOURCE_71", draft.read_text("utf-8"))
        status, out, _ = self.execute(
            "mobile-draft-init", "--source", str(self.source), "--output", str(draft),
        )
        self.assertEqual(status, 2)
        self.assertFalse(out)
        self.assertEqual(json.loads(draft.read_text("utf-8")), template)
        template["edits"] = {"s0": "PRIVATE_AFTER_72 from template"}
        draft.write_text(json.dumps(template), encoding="utf-8")
        status, out, err = self.execute(
            "mobile-patch-create", "--source", str(self.source),
            "--edits", str(draft), "--output", str(self.patch),
        )
        self.assertEqual(status, 0, err)
        self.assert_private_output(out)
        self.assertEqual(self.source.read_bytes(), initial)

    def test_stale_draft_rejected_even_when_project_and_segment_id_match(self):
        self.document["segments"][0]["text"] = "PRIVATE_SOURCE_71 changed after draft"
        self.source.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")
        status, output, error = self.execute(
            "mobile-patch-create", "--source", str(self.source),
            "--edits", str(self.edits), "--output", str(self.patch),
        )
        self.assertEqual(status, 2)
        self.assertFalse(output)
        self.assert_private_output(error)
        self.assertFalse(self.patch.exists())

    def test_old_unbound_v1_draft_fails_closed(self):
        self.draft["schema"] = "videonotes-mobile-edit-draft-v1"
        self.draft.pop("source_sha256")
        self.write_draft()
        status, output, error = self.execute(
            "mobile-patch-create", "--source", str(self.source),
            "--edits", str(self.edits), "--output", str(self.patch),
        )
        self.assertEqual(status, 2)
        self.assertFalse(output)
        self.assertNotIn("Traceback", error)
        self.assertFalse(self.patch.exists())

    def test_source_changed_during_creation_cannot_publish_patch(self):
        import videonotes.cli as module
        original = module.read_mobile_edit_draft_file
        initial = self.source.read_bytes()

        def simulate_source_mutation(*args, **kwargs):
            result = original(*args, **kwargs)
            self.document["segments"][0]["text"] = "CHANGED_SOURCE_BEFORE_PUBLICATION"
            self.source.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")
            return result

        with patch.object(module, "read_mobile_edit_draft_file",
                          side_effect=simulate_source_mutation):
            status, output, error = self.execute(
                "mobile-patch-create", "--source", str(self.source),
                "--edits", str(self.edits), "--output", str(self.patch),
            )
        self.assertEqual(status, 2)
        self.assertFalse(output)
        self.assertFalse(self.patch.exists())
        self.assertNotEqual(self.source.read_bytes(), initial)
        self.assertFalse(any(x.name.startswith(".vn-mobile-patch-")
                             for x in self.source.parent.iterdir()))
        self.assertNotIn("Traceback", error)


    def test_changed_draft_during_patch_publication_fails_without_partial_output(self):
        import os
        import videonotes.cli as module

        original_publish = module.export_mobile_corrections_file
        original_draft = self.edits.read_bytes()
        initial_source = self.source.read_bytes()

        def change_draft_after_validation(*args, **kwargs):
            # Identical byte count and preserved mtime: file timestamp/size
            # comparisons cannot substitute for a cryptographic fingerprint.
            old = self.edits.stat()
            updated = original_draft.replace(b"PRIVATE_AFTER_72", b"PRIVATE_AFTER_73")
            self.assertEqual(len(updated), len(original_draft))
            self.assertNotEqual(updated, original_draft)
            self.edits.write_bytes(updated)
            os.utime(self.edits, ns=(old.st_atime_ns, old.st_mtime_ns))
            return original_publish(*args, **kwargs)

        with patch.object(module, "export_mobile_corrections_file",
                          side_effect=change_draft_after_validation):
            code, output, error = self.execute(
                "mobile-patch-create", "--source", str(self.source),
                "--edits", str(self.edits), "--output", str(self.patch),
            )
        self.assertEqual(code, 2)
        self.assertFalse(output)
        self.assertFalse(self.patch.exists())
        self.assertEqual(self.source.read_bytes(), initial_source)
        self.assertNotIn("Traceback", error)
        self.assert_private_output(error)
        self.assertFalse(any(item.name.startswith(".vn-mobile-patch-")
                             for item in self.source.parent.iterdir()))

    def test_removed_draft_during_patch_publication_cannot_publish(self):
        import videonotes.cli as module

        original_publish = module.export_mobile_corrections_file
        source_before = self.source.read_bytes()

        def remove_draft_after_validation(*args, **kwargs):
            self.edits.unlink()
            return original_publish(*args, **kwargs)

        with patch.object(module, "export_mobile_corrections_file",
                          side_effect=remove_draft_after_validation):
            code, output, error = self.execute(
                "mobile-patch-create", "--source", str(self.source),
                "--edits", str(self.edits), "--output", str(self.patch),
            )
        self.assertEqual(code, 2)
        self.assertFalse(output)
        self.assertFalse(self.patch.exists())
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertNotIn("Traceback", error)
        self.assert_private_output(error)
        self.assertFalse(any(item.name.startswith(".vn-mobile-patch-")
                             for item in self.source.parent.iterdir()))

    def test_exact_draft_snapshot_digest_from_same_validated_bytes(self):
        from videonotes.mobile_import import read_mobile_edit_draft_file
        edits, digest = read_mobile_edit_draft_file(
            self.document, self.edits, source_sha256=self.draft["source_sha256"],
            include_digest=True,
        )
        self.assertEqual(edits, self.draft["edits"])
        self.assertEqual(digest, hashlib.sha256(self.edits.read_bytes()).hexdigest())
        self.assertEqual(
            read_mobile_edit_draft_file(self.document, self.edits,
                                        source_sha256=self.draft["source_sha256"]),
            edits,
        )


    def test_mobile_draft_check_reports_only_counts_without_writing_files(self):
        raw_source = self.source.read_bytes()
        raw_draft = self.edits.read_bytes()
        status, out, err = self.execute(
            "mobile-draft-check", "--source", str(self.source),
            "--edits", str(self.edits),
        )
        self.assertEqual(status, 0, err)
        report = json.loads(out)
        self.assertEqual(report["schema"], "videonotes-mobile-edit-draft-v2")
        self.assertEqual(report["segments"], 2)
        self.assertEqual(report["submitted_edits"], 1)
        self.assertEqual(report["actual_changes"], 1)
        self.assertEqual(report["unchanged_edits"], 0)
        self.assertTrue(report["read_only"])
        self.assert_private_output(out)
        self.assertEqual(err, "")
        self.assertFalse(self.patch.exists())
        self.assertEqual(self.source.read_bytes(), raw_source)
        self.assertEqual(self.edits.read_bytes(), raw_draft)

        self.draft["edits"]["s1"] = self.document["segments"][1]["text"]
        self.write_draft()
        status, out, err = self.execute(
            "mobile-draft-check", "--source", str(self.source),
            "--edits", str(self.edits),
        )
        self.assertEqual(status, 0, err)
        self.assertEqual(json.loads(out)["unchanged_edits"], 1)
        self.assertEqual(json.loads(out)["actual_changes"], 1)

    def test_mobile_draft_check_rejects_stale_or_duplicate_edits(self):
        self.draft["source_sha256"] = "0" * 64
        self.write_draft()
        status, out, err = self.execute(
            "mobile-draft-check", "--source", str(self.source),
            "--edits", str(self.edits),
        )
        self.assertEqual(status, 2)
        self.assertFalse(out)
        self.assert_private_output(err)
        self.assertFalse(self.patch.exists())
        self.draft["source_sha256"] = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.write_draft()
        corrupt = self.edits.read_bytes().replace(b'"s0":', b'"s0":"another","s0":')
        self.edits.write_bytes(corrupt)
        status, out, err = self.execute(
            "mobile-draft-check", "--source", str(self.source),
            "--edits", str(self.edits),
        )
        self.assertEqual(status, 2)
        self.assertFalse(out)
        self.assertNotIn("Traceback", err)

    def test_mobile_draft_check_detects_mutation_after_validation(self):
        import videonotes.cli as module
        original = module.read_mobile_edit_draft_file

        def mutate_after_read(*args, **kwargs):
            data = original(*args, **kwargs)
            self.edits.write_bytes(self.edits.read_bytes().replace(
                b"PRIVATE_AFTER_72", b"PRIVATE_AFTER_73"
            ))
            return data

        with patch.object(module, "read_mobile_edit_draft_file",
                          side_effect=mutate_after_read):
            status, out, err = self.execute(
                "mobile-draft-check", "--source", str(self.source),
                "--edits", str(self.edits),
            )
        self.assertEqual(status, 2)
        self.assertFalse(out)
        self.assertFalse(self.patch.exists())
        self.assert_private_output(err)

    def test_mobile_patch_check_rejects_changed_patch_after_first_preview(self):
        import videonotes.cli as module
        status, out, err = self.execute(
            "mobile-patch-create", "--source", str(self.source),
            "--edits", str(self.edits), "--output", str(self.patch),
        )
        self.assertEqual(status, 0, err)
        original = module.import_mobile_corrections_file
        source_before = self.source.read_bytes()

        def swap_patch_after_preview(*args, **kwargs):
            preview = original(*args, **kwargs)
            contents = self.patch.read_bytes()
            replacement = contents.replace(b"PRIVATE_AFTER_72", b"PRIVATE_AFTER_73")
            self.assertEqual(len(replacement), len(contents))
            self.patch.write_bytes(replacement)
            return preview

        with patch.object(module, "import_mobile_corrections_file",
                          side_effect=swap_patch_after_preview):
            status, out, err = self.execute(
                "mobile-patch-check", "--source", str(self.source),
                "--file", str(self.patch),
            )
        self.assertEqual(status, 2)
        self.assertFalse(out)
        self.assertNotIn("Traceback", err)
        self.assert_private_output(err)
        self.assertEqual(self.source.read_bytes(), source_before)



if __name__ == "__main__":
    unittest.main()
