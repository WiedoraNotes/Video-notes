"""Synthetic local subprocess tests; no actual GGUF or factual model QA."""
from __future__ import annotations

import inspect
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from videonotes.errors import VideoNotesError
from videonotes.semantic_draft import create_semantic_draft
from videonotes.semantic_process import MAX_REPLY_BYTES, run_bounded_llama


class BoundedLlamaProcessTest(unittest.TestCase):
    def test_default_semantic_draft_uses_bounded_process_runner(self):
        signature = inspect.signature(create_semantic_draft)
        self.assertIs(signature.parameters["runner"].default, run_bounded_llama)

    def test_real_local_subprocess_stdout_and_redacted_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.txt"
            with path.open("wb") as output:
                result = run_bounded_llama(
                    [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'OK');sys.stderr.write('PRIVATE_ERROR')"],
                    stdout=output, timeout=10,
                )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), b"OK")
            self.assertNotIn(b"PRIVATE_ERROR", path.read_bytes())

    def test_oversized_stdout_stops_child_without_unbounded_temp_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.bin"
            command = [sys.executable, "-c",
                       f"import sys;sys.stdout.buffer.write(b'A'*{MAX_REPLY_BYTES+10000});sys.stdout.flush()"]
            with path.open("wb") as output, self.assertRaisesRegex(VideoNotesError, "nadmier"):
                run_bounded_llama(command, stdout=output, timeout=10)
            self.assertLessEqual(path.stat().st_size, MAX_REPLY_BYTES)

    def test_silent_hanging_child_times_out_and_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.bin"
            with path.open("wb") as output, self.assertRaises(subprocess.TimeoutExpired):
                run_bounded_llama(
                    [sys.executable, "-c", "import time;time.sleep(2)"],
                    stdout=output, timeout=0.15,
                )
            self.assertEqual(path.stat().st_size, 0)

    def test_nonzero_local_exit_is_reported_without_stdout_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.bin"
            with path.open("wb") as output:
                result = run_bounded_llama(
                    [sys.executable, "-c", "import sys;sys.exit(9)"],
                    stdout=output, timeout=10,
                )
            self.assertEqual(result.returncode, 9)

    def test_metrics_runner_reuses_bounded_stdout_and_nonfictional_metrics(self):
        from scripts.semantic_gguf_acceptance import MetricsRunner
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.bin"
            runner = MetricsRunner()
            with path.open("wb") as output:
                result = runner(
                    [sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'VALID')"],
                    stdout=output, stdin=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, shell=False, timeout=10, check=False,
                )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), b"VALID")
            self.assertEqual(len(runner.runs), 1)
            self.assertGreaterEqual(runner.runs[0]["elapsed_s"], 0)
            self.assertIn("sampled_cpu_s", runner.runs[0])


if __name__ == "__main__":
    unittest.main()
