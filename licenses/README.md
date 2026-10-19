# Third-party license copies and provenance

Reviewed for source-release preparation on **2026-10-19**. These notices do not replace the licenses accompanying the exact versions installed on another computer. This directory is a notice collection, not a complete binary SBOM or a claim that all dependencies have been audited.

| Component | Role | License / included text | Upstream reference |
| --- | --- | --- | --- |
| OpenAI Whisper | Original speech models and implementation | [MIT](openai-whisper-LICENSE) | [Official LICENSE](https://github.com/openai/whisper/blob/main/LICENSE) |
| faster-whisper 1.2.1 | Optional CPU speech adapter | [MIT](faster-whisper-LICENSE) | [v1.2.1 LICENSE](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/LICENSE) |
| CTranslate2 | faster-whisper inference dependency | [MIT](ctranslate2-LICENSE) | [v4.8.3 LICENSE](https://github.com/OpenNMT/CTranslate2/blob/v4.8.3/LICENSE) |
| MLX / MLX Examples / mlx-whisper | Optional Apple Silicon path | [MIT notice shared by MLX and MLX Examples](mlx-LICENSE) | [MLX](https://github.com/ml-explore/mlx/blob/main/LICENSE), [MLX Examples](https://github.com/ml-explore/mlx-examples/blob/main/LICENSE), [mlx-whisper 0.4.3 metadata](https://pypi.org/project/mlx-whisper/0.4.3/) |
| PyAV | Optional audio decoding dependency | [BSD-3-Clause](pyav-LICENSE.txt) | [Official LICENSE](https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt) |
| imageio-ffmpeg 0.6.0 | Optional FFmpeg discovery/executable package | [BSD-2-Clause wrapper license](imageio-ffmpeg-LICENSE) | [v0.6.0 LICENSE](https://github.com/imageio/imageio-ffmpeg/blob/v0.6.0/LICENSE) |
| ReportLab 4.4.10 | Optional PDF export | [BSD-style text](reportlab-LICENSE) | License copied from the installed 4.4.10 wheel's `dist-info/licenses/LICENSE`; [official PyPI distribution](https://pypi.org/project/reportlab/4.4.10/) |

## Model weights

No weights are included. Optional setup downloads `Systran/faster-whisper-small`; its [model card](https://huggingface.co/Systran/faster-whisper-small) declares MIT and identifies the OpenAI Whisper conversion. The installer records the resolved model revision and file hashes locally in `model-manifest.json`. A different model or conversion needs its own model-card/license review; the app's MIT license does not relicense it.

## Binary and transitive dependencies

The imageio-ffmpeg wrapper license is **not** the license for every FFmpeg binary. FFmpeg builds can involve LGPL/GPL and other obligations; consult [FFmpeg's official legal page](https://ffmpeg.org/legal.html) and the exact build's source/notices before redistributing binaries. This source repository includes no FFmpeg executable, PyAV libraries, Python runtime, dependency wheels or weights.

The optional installer obtains wheels on the recipient's computer and collects their available license files and version metadata under `.portable/licenses/`. NumPy, Hugging Face Hub, tokenizers, ONNX Runtime, PyYAML, Pillow and other resolved dependencies keep their own terms. That installed collection is not bundled here and is not a complete compliance audit. Python/portable Python distributions retain their own licenses: [Python license](https://docs.python.org/3/license.html), [python-build-standalone](https://github.com/astral-sh/python-build-standalone).

System fonts are not redistributed. Local PDF rendering can use/embed subsets from installed fonts; choose fonts you may use. No course slides, recordings, personal notes or third-party service logos are licensed by this source release.
