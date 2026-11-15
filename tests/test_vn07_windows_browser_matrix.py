"""No hardware claims: pure tests of the optional physical Windows automation kit."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.vn07_windows_browser_matrix import (
    BROWSERS, SCHEMA, browser_executable, current_checkout,
    publish_report, run_matrix,
)


class VN07WindowsBrowserMatrixTests(unittest.TestCase):
    def programs(self):
        return {"node": r"C:\Tools\node.exe", "chrome": r"C:\Browsers\chrome.exe",
                "edge": r"C:\Browsers\msedge.exe", "firefox": r"C:\Browsers\firefox.exe",
                "geckodriver": r"C:\Tools\geckodriver.exe"}

    def test_three_automated_passes_stay_automated_only(self):
        calls = []

        def fake(command, extra_env, timeout):
            calls.append((command, extra_env, timeout))
            return 0

        result = run_matrix(self.programs(), fake)
        self.assertEqual(set(result), set(BROWSERS))
        self.assertEqual([x["status"] for x in result.values()], ["AUTOMATED_PASS"] * 3)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call[2] == 240 for call in calls))
        self.assertEqual(calls[0][1], {"CHROME_BIN": r"C:\Browsers\chrome.exe"})
        self.assertEqual(calls[1][1], {"CHROME_BIN": r"C:\Browsers\msedge.exe"})
        self.assertEqual(calls[2][1], {"GECKODRIVER_BIN": r"C:\Tools\geckodriver.exe",
                                       "FIREFOX_BIN": r"C:\Browsers\firefox.exe"})
        self.assertTrue(calls[0][0][-1].endswith("browser-smoke.cjs"))
        self.assertTrue(calls[2][0][-1].endswith("firefox-smoke.cjs"))
        self.assertNotIn("PHYSICAL_PASS", json.dumps(result))

    def test_missing_executable_stays_not_run_without_launching(self):
        programs = {"node": r"C:\Tools\node.exe", "chrome": None, "edge": None,
                    "firefox": r"C:\Browsers\firefox.exe", "geckodriver": None}
        result = run_matrix(programs, lambda *_: self.fail("Runner must not launch"))
        self.assertTrue(all(v["status"] == "NOT_RUN" for v in result.values()))
        self.assertTrue(all(v["reason"] == "MISSING_EXECUTABLE" for v in result.values()))

    def test_nonzero_timeout_and_start_failure_cannot_be_pass(self):
        seen = []

        def fake(command, environment, timeout):
            seen.append(environment)
            if "CHROME_BIN" in environment and environment["CHROME_BIN"].endswith("chrome.exe"):
                return 9
            if "CHROME_BIN" in environment:
                raise subprocess.TimeoutExpired(command, timeout)
            raise OSError("Synthetic process error")

        result = run_matrix(self.programs(), fake)
        self.assertEqual(result["chrome"], {"status": "AUTOMATED_FAIL", "reason": "NONZERO_EXIT"})
        self.assertEqual(result["edge"], {"status": "AUTOMATED_FAIL", "reason": "TIMEOUT"})
        self.assertEqual(result["firefox"], {"status": "NOT_RUN", "reason": "PROCESS_START_FAILED"})
        self.assertEqual(len(seen), 3)

    def test_git_must_be_develop_with_no_dirty_tracked_code(self):
        sha = "a" * 40

        def make_invoke(branch, dirty=""):
            return lambda command: {
                "rev-parse": sha, "branch": branch, "status": dirty
            }[command[1]]

        self.assertEqual(current_checkout(make_invoke("develop")), ("develop", sha))
        for branch, dirty in (("main", ""), ("develop", " M web/app.js")):
            with self.subTest(branch=branch, dirty=dirty):
                with self.assertRaises(ValueError):
                    current_checkout(make_invoke(branch, dirty))

    def test_report_creation_no_clobber_and_redacted_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "vn07-private.json"
            report = {
                "schema": SCHEMA,
                "tests": {name: {"status": "AUTOMATED_PASS"} for name in BROWSERS},
                "manual_web01": "NOT_RUN", "manual_web02": "NOT_RUN",
                "nvda_human_review": "NOT_RUN",
                "hardware_attested": False, "stage_status_updated": False,
            }
            publish_report(destination, report)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), report)
            payload = destination.read_text(encoding="utf-8")
            self.assertNotIn(str(destination), payload)
            self.assertFalse(report["hardware_attested"])
            with self.assertRaises(ValueError):
                publish_report(destination, report)
            self.assertEqual(destination.read_text(encoding="utf-8"), payload)
            with self.assertRaises(ValueError):
                publish_report(Path(temp) / "bad.txt", report)
            existing = Path(temp) / "root.json"
            existing.symlink_to(destination)
            with self.assertRaises(ValueError):
                publish_report(existing, report)

    def test_symlink_executable_not_selected_and_never_downloaded(self):
        with tempfile.TemporaryDirectory() as temp:
            exe = Path(temp) / "simulated.exe"
            exe.write_text("synthetic", encoding="utf-8")
            link = Path(temp) / "shortcut.exe"
            try:
                link.symlink_to(exe)
            except (OSError, NotImplementedError):
                self.skipTest("No symlink support on this runner")
            with mock.patch("shutil.which", return_value=None):
                self.assertIsNone(browser_executable("chrome", str(link)))

    @unittest.skipIf(os.name == "nt", "This negative check runs on non-Windows CI")
    def test_real_cli_refuses_non_windows_instead_of_faking_acceptance(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "vn07_windows_browser_matrix.py"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "report.json"
            run = subprocess.run([sys.executable, str(script), "--output", str(output)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, check=False)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("Physical Windows only", run.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
