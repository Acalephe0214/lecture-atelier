"""QTA track-selection regressions; no model, downloads or real recordings."""
import io
import json
import sys
from types import SimpleNamespace
import unittest
import wave
from unittest.mock import patch

import local_transcription
import local_repair


class QuickTimeTrackTests(unittest.TestCase):
    def test_full_worker_selects_first_audio_not_spatial_track(self):
        commands = []

        def decode(command, **kwargs):
            commands.append(command)
            with wave.open(str(command[-1]), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b"\0\0" * 16000)

        data = {"audio_path": "synthetic.qta", "config": {"language": "auto", "model_path": "unused"}}
        with patch("local_transcription.sys.stdin", io.StringIO(json.dumps(data))), patch("local_transcription.sys.stdout", io.StringIO()), patch("local_transcription.subprocess.check_output", return_value=b"1"), patch("local_transcription.subprocess.run", side_effect=decode), patch("local_transcription.shutil.which", return_value="ffmpeg"):
            local_transcription.worker()
        self.assertTrue(commands)
        for command in commands:
            self.assertEqual(command[command.index("-map") + 1], "0:a:0")
            self.assertIn("-vn", command)

    def test_repair_worker_uses_same_audio_track(self):
        model = SimpleNamespace(transcribe=lambda *args, **kwargs: {"segments": []})
        data = {"path": "synthetic.qta", "config": {"model_path": "unused", "language": "auto"}, "row": {"start": 0, "end": 1}, "strategy": 0}
        with patch.dict(sys.modules, {"mlx_whisper": model}), patch("local_repair.sys.stdout", io.StringIO()), patch("local_repair.media_duration", return_value=1), patch("local_repair.subprocess.run") as decode:
            local_repair.worker(data)
        self.assertTrue(decode.called)
        for args, kwargs in decode.call_args_list:
            command = args[0]
            self.assertEqual(command[command.index("-map") + 1], "0:a:0")
            self.assertIn("-vn", command)


if __name__ == "__main__":
    unittest.main()
