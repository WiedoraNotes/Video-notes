from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videonotes.asr import WhisperCpp, parse_whisper_output
from videonotes.stable_local_read import MAX_ASR_JSON_BYTES, read_stable_local_json
from videonotes.errors import VideoNotesError


class WhisperAdapterTest(unittest.TestCase):
    def test_timestamp_offset_and_unicode(self):
        payload = {"transcription": [
            {"offsets": {"from": 50, "to": 450}, "text": " Zażółć gęślą jaźń! "},
            {"offsets": {"from": 450, "to": 700}, "text": " Dalej."}]}
        out = parse_whisper_output(payload, offset_ms=30000, duration_ms=800)
        self.assertEqual(out[0], {"start_ms": 30050, "end_ms": 30450, "text": "Zażółć gęślą jaźń!"})
        self.assertEqual(out[-1]["end_ms"], 30700)

    def test_asr_malformed_or_out_of_window_rejected(self):
        for item in [[], {"transcription": "bad"}, {"transcription": [{"text": "x", "offsets": {"from": -1, "to": 5}}]},
                     {"transcription": [{"text": "x", "offsets": {"from": 1, "to": 5000}}]},
                     {"transcription": [{"text": "x", "offsets": {"from": True, "to": 10}}]}]:
            with self.subTest(item=item), self.assertRaises(VideoNotesError):
                parse_whisper_output(item, offset_ms=0, duration_ms=1000)

    def test_exact_duplicates_removed_without_dropping_repeated_speech(self):
        payload = {"transcription": [
            {"offsets": {"from": 10, "to": 90}, "text": " tak "},
            {"offsets": {"from": 10, "to": 90}, "text": "tak"},
            {"offsets": {"from": 100, "to": 180}, "text": "tak"},
            {"offsets": {"from": 10, "to": 90}, "text": "inny tekst"},
        ]}
        result = parse_whisper_output(payload, offset_ms=1000, duration_ms=200)
        self.assertEqual(len(result), 3)
        self.assertEqual([row["text"] for row in result], ["tak", "inny tekst", "tak"])
        self.assertEqual([row["start_ms"] for row in result], [1010, 1010, 1100])

    def test_whisper_json_rejects_duplicate_keys_and_symlinked_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = root / "model.bin"
            model.write_bytes(b"test-only")
            executable = root / "whisper-cli"
            executable.write_text("mock")
            external = root / "external.json"
            external.write_text('{"transcription":[]}')
            def duplicate_json(args, **kwargs):
                Path(args[args.index("--output-file") + 1] + ".json").write_text(
                    '{"transcription":[],"transcription":[{"text":"UNTRUSTED","offsets":{"from":0,"to":5}}]}'
                )
            with patch("videonotes.asr.executable", return_value=str(executable)), patch(
                "videonotes.asr._run", side_effect=duplicate_json
            ):
                with self.assertRaisesRegex(VideoNotesError, "powielone pola"):
                    WhisperCpp(str(executable), model).transcribe(root / "input.wav",
                                                                 language="pl", offset_ms=0, duration_ms=500)
            def symlink_json(args, **kwargs):
                target = Path(args[args.index("--output-file") + 1] + ".json")
                try:
                    target.symlink_to(external)
                except (OSError, NotImplementedError):
                    raise unittest.SkipTest("Symlink unavailable on this runner")
            with patch("videonotes.asr.executable", return_value=str(executable)), patch(
                "videonotes.asr._run", side_effect=symlink_json
            ):
                with self.assertRaisesRegex(VideoNotesError, "niedozwolony"):
                    WhisperCpp(str(executable), model).transcribe(root / "input.wav",
                                                                 language="pl", offset_ms=0, duration_ms=500)

    def test_whisper_cpp_call_never_uses_shell_or_network(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            model = base / "model.bin"
            executable = base / "whisper-cli"
            wav = base / "input.wav"
            model.write_bytes(b"fake-model-test-no-real-asr")
            executable.write_text("placeholder")
            wav.write_bytes(b"not-a-real-wav-in-mock")
            calls = []
            def fake_run(args, **kwargs):
                calls.append(args)
                index = args.index("--output-file")
                Path(args[index + 1] + ".json").write_text('{"transcription":[{"text":"Hello","offsets":{"from":10,"to":100}}]}', encoding="utf-8")
            with patch("videonotes.asr.executable", return_value=str(executable)), patch("videonotes.asr._run", side_effect=fake_run):
                asr = WhisperCpp(str(executable), model)
                result = asr.transcribe(wav, language="en", offset_ms=1000, duration_ms=300)
            self.assertEqual(result[0]["start_ms"], 1010)
            self.assertIn("--no-gpu", calls[0])
            self.assertIn("--no-prints", calls[0])
            self.assertIn("--output-json", calls[0])
            self.assertNotIn("http", " ".join(calls[0]))


    def test_whisper_fails_closed_on_bad_json_numbers_depth_and_encoding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = root / "model.bin"
            model.write_bytes(b"model-synthetic-only")
            exe = root / "whisper-cli"
            exe.write_text("synthetic", encoding="utf-8")
            wav = root / "input.wav"
            wav.write_bytes(b"private-synthetic-media")
            examples = (
                b'{"transcription":[],"metadata":NaN}',
                b'{"transcription":[],"metadata":Infinity}',
                b'{"transcription":[],"metadata":-Infinity}',
                b'{"transcription":[],"metadata":' + b"[" * 15000 + b"0" + b"]" * 15000 + b"}",
                b'{"transcription":[],"metadata":' + b"8" * 8000 + b"}",
                b'{"transcription":[{"text":"' + bytes((0xff,)) +
                b'","offsets":{"from":0,"to":25}}]}',
                bytes((0xff, 0xfe)),
            )
            def make_fake(raw):
                def runner(args, **kwargs):
                    Path(args[args.index("--output-file") + 1] + ".json").write_bytes(raw)
                return runner
            with patch("videonotes.asr.executable", return_value=str(exe)):
                engine = WhisperCpp(str(exe), model)
                for raw in examples:
                    with self.subTest(length=len(raw)), patch("videonotes.asr._run", side_effect=make_fake(raw)):
                        with self.assertRaises(VideoNotesError) as error:
                            engine.transcribe(wav, language="pl", offset_ms=0, duration_ms=100)
                        self.assertNotIn(str(root), str(error.exception))
                        self.assertEqual(wav.read_bytes(), b"private-synthetic-media")

    def test_whisper_rejects_oversized_text_invalid_unicode_and_bad_chunk_time(self):
        good = lambda t: {"transcription": [{"text": t, "offsets": {"from": 0, "to": 10}}]}
        bad_text = ("X" * 10001, "😀" * 5001, chr(0xD800), "Ż" + chr(0) + "ółw")
        for value in bad_text:
            with self.subTest(value=repr(value[:25])):
                with self.assertRaisesRegex(VideoNotesError, "Unicode|limitem"):
                    parse_whisper_output(good(value), offset_ms=0, duration_ms=100)
        self.assertEqual(parse_whisper_output(good("😀" * 5000), offset_ms=0, duration_ms=100)[0]["text"],
                         "😀" * 5000)
        for offset, duration in ((True, 100), (-1, 100), (0, 0),
                                 (0, False), (86400000, 1), (0, 86400001)):
            with self.subTest(offset=offset, duration=duration):
                with self.assertRaisesRegex(VideoNotesError, "czas fragmentu"):
                    parse_whisper_output(good("OK"), offset_ms=offset, duration_ms=duration)

    def test_stable_reader_supports_larger_asr_ceiling_without_raising_import_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "local-model.json"
            content = b'{"transcription":[]}'
            file.write_bytes(content)
            raw, digest = read_stable_local_json(file, max_bytes=MAX_ASR_JSON_BYTES)
            self.assertEqual(raw, content)
            self.assertEqual(digest, hashlib.sha256(content).hexdigest())
            with self.assertRaises(VideoNotesError):
                read_stable_local_json(file, max_bytes=len(content) - 1)
            for invalid in (0, False, -1, MAX_ASR_JSON_BYTES + 1):
                with self.subTest(invalid=invalid), self.assertRaises(VideoNotesError):
                    read_stable_local_json(file, max_bytes=invalid)

    def test_whisper_rejects_json_file_changed_during_read_without_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = root / "model.bin"
            model.write_bytes(b"fake-model")
            exe = root / "whisper-cli"
            exe.write_text("synthetic", encoding="utf-8")
            wav = root / "input.wav"
            wav.write_bytes(b"unchanged-source")
            def fake_run(args, **kwargs):
                Path(args[args.index("--output-file") + 1] + ".json").write_bytes(
                    b'{"transcription":[{"text":"secret speech","offsets":{"from":0,"to":10}}]}'
                )
            with patch("videonotes.asr.executable", return_value=str(exe)), \
                    patch("videonotes.asr._run", side_effect=fake_run), \
                    patch("videonotes.asr.read_stable_local_json",
                          side_effect=VideoNotesError("Changed while reading")) as stable:
                with self.assertRaisesRegex(VideoNotesError, "Changed while reading"):
                    WhisperCpp(str(exe), model).transcribe(wav, language="pl",
                                                         offset_ms=0, duration_ms=100)
                self.assertEqual(stable.call_args.kwargs, {"max_bytes": MAX_ASR_JSON_BYTES})
            self.assertEqual(wav.read_bytes(), b"unchanged-source")


if __name__ == "__main__":
    unittest.main()
