"""All fixed local-task messages need explicit English, not a raw fallback."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')


class DiagnosticCatalogTests(unittest.TestCase):
    @unittest.skipUnless(Path(NODE).is_file(), 'Node required for the JS catalog')
    def test_fixed_backend_task_diagnostics_have_translations(self):
        messages=json.loads(subprocess.check_output([NODE,'-e','process.stdout.write(JSON.stringify({...require("./static/i18n-en.js"),...Object.fromEntries(Object.entries(require("./static/ui-copy.js")).map(([key,value])=>[key,value.en]))}))'],cwd=ROOT,text=True))
        files=['local_transcription.py','local_repair.py','audio_processing.py','core/asr_guard.py','core/audio_prepare.py',
               'note_jobs.py','note_checkpoints.py','recycle.py','correction_jobs.py','asr_checkpoints.py','core/languages.py','core/local_engine.py','core/mixed_asr.py','store.py']
        missing=[]
        for name in files:
            tree=ast.parse((ROOT/name).read_text())
            fragments={id(part) for node in ast.walk(tree) if isinstance(node,ast.JoinedStr) for part in node.values}
            for node in ast.walk(tree):
                if not isinstance(node,ast.Constant) or not isinstance(node.value,str) or id(node) in fragments:
                    continue
                value=node.value
                if len(value)<6 or not any('\u4e00' <= char <= '\u9fff' for char in value):
                    continue
                if value.startswith('【转写缺口') or value.startswith('。请回听或另行补转'):
                    continue  # Explicitly handled by metadata-gated sourceText.
                if value not in messages:
                    missing.append((name,value))
                else:
                    self.assertFalse(any('\u4e00' <= char <= '\u9fff' for char in messages[value]),(name,value))
        self.assertEqual(missing,[])
