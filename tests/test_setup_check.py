import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import check_setup
from store import Store


class SetupCheckTests(unittest.TestCase):
    def test_default_check_does_not_create_runtime_or_load_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch("check_setup.ROOT",root),patch("check_setup.importlib.util.find_spec",return_value=None):
                result=check_setup.inspect(root/"model")
            self.assertFalse((root/".runtime").exists())
            self.assertFalse(result["inference_tested"])
            self.assertFalse(result["api_keys_needed_for_basic_app"])
            self.assertNotIn("api_key",result)
            self.assertFalse(result["model_files_present"])

    def test_intel_and_rosetta_do_not_claim_local_mlx_ready(self):
        with patch("check_setup.platform.system",return_value="Darwin"),patch("check_setup.platform.machine",return_value="x86_64"),patch("check_setup.subprocess.check_output",return_value="1\n"):
            result=check_setup.inspect()
        self.assertTrue(result["apple_silicon_hardware"])
        self.assertFalse(result["native_apple_silicon_python"])
        self.assertFalse(result["local_asr_prerequisites_present"])

    def test_explicit_configuration_retains_private_api_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); model=root/"model"; model.mkdir()
            (model/"config.json").write_text('{"n_vocab":51866}')
            (model/"weights.npz").write_bytes(b"synthetic model marker; never loaded")
            store=Store(root/".runtime")
            store.update_settings({"llm":{"base_url":"https://example.invalid/v1","model":"synthetic","api_key":"synthetic-secret"}})
            with patch("check_setup.ROOT",root),patch("check_setup.platform.system",return_value="Darwin"),patch("check_setup.platform.machine",return_value="arm64"),patch("check_setup.shutil.which",return_value="/synthetic/ffmpeg"),patch("check_setup.importlib.util.find_spec",return_value=object()):
                result=check_setup.configure_local(model)
            self.assertTrue(result["configured"])
            self.assertFalse(result["inference_tested"])
            self.assertEqual(store.private_settings()["llm"]["api_key"],"synthetic-secret")
            self.assertNotIn("synthetic-secret",json.dumps(result))
            self.assertEqual(store.public_settings()["local_asr"]["model_path"],str(model))

    def test_missing_prerequisites_never_write_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch("check_setup.ROOT",root),patch("check_setup.platform.system",return_value="Windows"),patch("check_setup.shutil.which",return_value=None):
                with self.assertRaises(ValueError): check_setup.configure_local(root/"no-model")
            self.assertFalse((root/".runtime").exists())


if __name__=="__main__":unittest.main()
