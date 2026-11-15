"""Synthetic physical-browser inputs are stable and never authorize a VN PASS."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from videonotes.errors import VideoNotesError
from videonotes.mobile_contract import parse_portable_export
from videonotes.mobile_corrections import parse_mobile_corrections


class VN07PhysicalFixtureTests(unittest.TestCase):
    def test_generation_contract_hashes_fail_closed_fixtures_and_no_overwrite(self):
        cli = Path(__file__).resolve().parents[1] / "scripts" / "vn07_acceptance_fixture.py"
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "new-fixtures"
            run = subprocess.run([sys.executable, str(cli), "--output", str(folder)],
                                 capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(run.stdout)
            self.assertEqual(report["schema"], "videonotes-vn07-synthetic-fixtures-v1")
            self.assertTrue(report["synthetic_only"])
            self.assertFalse(report["human_acceptance"])
            self.assertEqual(len(report["files"]), 6)
            for name, metadata in report["files"].items():
                blob = (folder / name).read_bytes()
                self.assertEqual(metadata["sha256"], hashlib.sha256(blob).hexdigest())
                self.assertEqual(metadata["bytes"], len(blob))
            self.assertEqual(json.loads((folder / "manifest.json").read_text(encoding="utf-8")), report)
            small = parse_portable_export((folder / "vn07-small.json").read_bytes())
            large = parse_portable_export((folder / "vn07-large-50000.json").read_bytes())
            self.assertEqual(len(small["segments"]), 3)
            self.assertEqual(len(large["segments"]), 50000)
            self.assertEqual(large["segments"][-1]["id"], "seg-49999")
            self.assertEqual(large["segments"][-1]["start_ms"], 49999 * 1500)
            self.assertLess((folder / "vn07-large-50000.json").stat().st_size, 20 * 1024 * 1024)
            corrected = parse_mobile_corrections(small, (folder / "vn07-corrections.json").read_bytes())
            self.assertEqual(corrected, {"seg-00001": "Zmieniony tekst wyłącznie do testu."})
            with self.assertRaises(VideoNotesError):
                parse_mobile_corrections(small, (folder / "vn07-foreign-corrections.json").read_bytes())
            with self.assertRaises(VideoNotesError):
                parse_portable_export((folder / "vn07-duplicate-key.json").read_bytes())
            with self.assertRaises(VideoNotesError):
                parse_portable_export((folder / "vn07-deeply-nested.json").read_bytes())

            before = {name: (folder / name).read_bytes() for name in report["files"]}
            rerun = subprocess.run([sys.executable, str(cli), "--output", str(folder)],
                                   capture_output=True, text=True, check=False)
            self.assertNotEqual(rerun.returncode, 0)
            self.assertIn("już istnieje", rerun.stderr)
            self.assertEqual({name: (folder / name).read_bytes() for name in report["files"]}, before)

    def test_symlink_parent_is_rejected_before_any_fixture_write(self):
        cli = Path(__file__).resolve().parents[1] / "scripts" / "vn07_acceptance_fixture.py"
        with tempfile.TemporaryDirectory() as temporary:
            real = Path(temporary) / "real"
            real.mkdir()
            symlink = Path(temporary) / "alias"
            try:
                symlink.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("This test system cannot create directory symlinks")
            run = subprocess.run([sys.executable, str(cli), "--output", str(symlink / "new")],
                                 capture_output=True, text=True, check=False)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((real / "new").exists())


if __name__ == "__main__":
    unittest.main()
