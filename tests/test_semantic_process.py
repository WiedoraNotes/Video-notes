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

class GGUFProvenanceTest(unittest.TestCase):
    """The inference call is mocked; these tests do not run a real GGUF."""

    def _inputs(self, directory):
        import struct
        folder = Path(directory)
        model = folder / "fake-model.gguf"
        model.write_bytes(struct.pack("<4sIQQ", b"GGUF", 3, 1, 0) + b"X")
        cli = folder / "fake-llama.exe"
        cli.write_bytes(b"synthetic binary content, not executable")
        return model, cli, folder / "private-results"

    def _draft(self, _project, output, *, model, llama_cli, runner):
        output.write_bytes(b"synthetic private draft")
        return {"model_sha256": "a" * 64, "sections": 1, "claims": 2}

    def _verify(self, _project, output):
        from videonotes.contracts import sha256_file
        return {
            "verified_source_citations": True, "source_sha256": "b" * 64,
            "document_sha256": sha256_file(output),
        }

    def test_report_binds_cli_transcript_and_draft_without_accepting_facts(self):
        import hashlib
        from unittest.mock import patch
        from scripts.semantic_gguf_acceptance import run
        with tempfile.TemporaryDirectory() as directory:
            model, cli, out = self._inputs(directory)
            with patch("scripts.semantic_gguf_acceptance.create_semantic_draft",
                       side_effect=self._draft) as called, patch(
                       "scripts.semantic_gguf_acceptance.verify_semantic_draft",
                       side_effect=self._verify):
                report = run(Path(directory), model, str(cli), out)
            self.assertEqual(report["llama_cli_sha256"], hashlib.sha256(cli.read_bytes()).hexdigest())
            self.assertEqual(report["source_sha256"], "b" * 64)
            self.assertEqual(report["draft_sha256"],
                             hashlib.sha256((out / "private-draft.json").read_bytes()).hexdigest())
            self.assertEqual(report["human_reviewed"], False)
            self.assertEqual(report["semantic_facts_verified"], False)
            self.assertIn("NOT_RUN", report["acceptance"])
            self.assertNotIn(str(cli), (out / "report.json").read_text("utf-8"))
            self.assertEqual(Path(called.call_args.kwargs["llama_cli"]).resolve(), cli.resolve())
            self.assertEqual(__import__("json").loads((out / "report.json").read_text("utf-8")), report)

    def test_refuse_changed_executable_without_writing_success_report(self):
        from unittest.mock import patch
        from scripts.semantic_gguf_acceptance import run
        with tempfile.TemporaryDirectory() as directory:
            model, cli, out = self._inputs(directory)
            def replace_cli(*args, **kwargs):
                cli.write_bytes(b"changed executable with the same size")  # changed after preflight
                return self._draft(*args, **kwargs)
            with patch("scripts.semantic_gguf_acceptance.create_semantic_draft",
                       side_effect=replace_cli), patch(
                       "scripts.semantic_gguf_acceptance.verify_semantic_draft",
                       side_effect=self._verify):
                with self.assertRaisesRegex(VideoNotesError, "zmieniły"):
                    run(Path(directory), model, str(cli), out)
            self.assertFalse((out / "report.json").exists())

    def test_refuse_changed_draft_without_writing_success_report(self):
        from unittest.mock import patch
        from scripts.semantic_gguf_acceptance import run
        with tempfile.TemporaryDirectory() as directory:
            model, cli, out = self._inputs(directory)
            def changed_draft(project, draft):
                report = self._verify(project, draft)
                draft.write_bytes(b"synthetic private draft altered")
                return report
            with patch("scripts.semantic_gguf_acceptance.create_semantic_draft",
                       side_effect=self._draft), patch(
                       "scripts.semantic_gguf_acceptance.verify_semantic_draft",
                       side_effect=changed_draft):
                with self.assertRaisesRegex(VideoNotesError, "zmieniły"):
                    run(Path(directory), model, str(cli), out)
            self.assertFalse((out / "report.json").exists())

    def test_refuse_symlink_result_directory(self):
        from unittest.mock import patch
        from scripts.semantic_gguf_acceptance import run
        with tempfile.TemporaryDirectory() as directory:
            model, cli, out = self._inputs(directory)
            real = Path(directory) / "real"
            real.mkdir()
            try:
                out.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("The platform does not permit symlink creation")
            with patch("scripts.semantic_gguf_acceptance.create_semantic_draft",
                       side_effect=self._draft):
                with self.assertRaisesRegex(VideoNotesError, "dowiązaniem"):
                    run(Path(directory), model, str(cli), out)
            self.assertFalse((real / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
