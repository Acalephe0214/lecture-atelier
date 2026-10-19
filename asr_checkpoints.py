"""Atomic private checkpoints, keyed to original audio and local model files."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from core import workflow
from core.asr_guard import VERSION
from audio_processing import fingerprint


class Checkpoints:
    def __init__(self, root):
        self.root = Path(root) / "asr-checkpoints"

    def path(self, key):
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("断点编号无效。")
        if self.root.is_symlink():
            raise ValueError("断点目录不能是软链接。")
        path = self.root / (key + ".json")
        if path.is_symlink():
            raise ValueError("断点文件不能是软链接。")
        return path

    @staticmethod
    def key(identity, source, config):
        model = Path(config["model_path"])
        versions = [fingerprint(model / "config.json")]
        for name in ("weights.npz", "weights.safetensors", "model.bin", "tokenizer.json"):
            if (model / name).is_file():
                versions.append(fingerprint(model / name))
        from core.languages import candidates
        from core.mixed_asr import VERSION as mixed_version
        parts = [identity, source, versions, config["language"], config.get("backend", "mlx"), VERSION]
        if candidates(config["language"]):
            parts.append(mixed_version)
        return workflow.digest(parts)

    def load(self, key):
        path = self.path(key)
        if not path.exists():
            return {"version": VERSION, "chunks": {}, "duration": None}
        try:
            if path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError()
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != VERSION or not isinstance(data.get("chunks"), dict):
                raise ValueError()
            return data
        except (OSError, ValueError, TypeError, AttributeError):
            raise ValueError("本地断点无法读取；可取消‘复用断点’后重跑，旧稿未改动。") from None

    def save(self, key, data):
        path = self.path(key)
        self.root.mkdir(exist_ok=True, mode=0o700)
        temporary = self.root / (".checkpoint-" + uuid4().hex + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
