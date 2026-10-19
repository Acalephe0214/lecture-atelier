"""Whisper language tokens; model support is not an accuracy guarantee."""
import json
from pathlib import Path

# OpenAI Whisper tokenizer language codes (multilingual models).
CODES = set("en zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms cs ro da hu ta no th ur hr bg lt la mi ml cy sk te fa lv bn sr az sl kn et mk br eu is hy ne mn bs kk sq sw gl mr pa si km sn yo so af oc ka be tg sd gu am yi lo uz fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha ba jw su yue".split())
COMMON = [("auto", "自动检测（每个片段）"), ("zh", "中文"), ("en", "英语"),
          ("zh_en", "中英混合（短窗识别）"), ("mix:fr,vi", "法语＋越南语（短窗识别）"), ("vi", "越南语"), ("fr", "法语"),
          ("de", "德语"), ("ja", "日语")]


def language(value):
    if isinstance(value, str) and value.startswith("mix:"):
        codes = value[4:].split(",")
        if 2 <= len(codes) <= 6 and len(set(codes)) == len(codes) and all(code in CODES for code in codes):
            return "mix:" + ",".join(sorted(codes))
        raise ValueError("混合语言请选择 2—6 种不同的 Whisper 语言；不接受 auto 或未知代码，不会自动上传。")
    if not isinstance(value, str) or value not in CODES | {"auto", "zh_en"}:
        raise ValueError("当前 Whisper 不支持这个语言代码。请导入其他识别工具生成的稿件，或另行配置兼容的转写网关；不会自动上传。")
    return value


def candidates(value):
    value = language(value)
    if value == "zh_en":
        return ("en", "zh")
    return tuple(value[4:].split(",")) if value.startswith("mix:") else ()


def decoder_language(value):
    value = language(value)
    return None if value == "auto" or candidates(value) else value


class LanguageUncertain(ValueError):
    """Safe, controlled message only; not a third-party model exception."""
    def __init__(self):
        super().__init__("所选混合语言的音频判断依据不足，请回听或使用单语局部补转")


def catalog():
    return {"common": [{"id": key, "label": label} for key, label in COMMON],
            "codes": sorted(CODES), "notice": "多语言课程可选择 2—6 种候选语言，在短窗内按音频判断解码语言；保留原语言，不翻译。语言分数是启发式依据，不保证同一句内混说准确；判断依据不足会标记回听。多语言会增加本地计算，未对所有语言组合做真实语音验收；不会自动上传。"}


def check_model(config):
    try:
        value = json.loads((Path(config["model_path"]) / "config.json").read_text())
    except (ValueError, OSError):
        raise ValueError("无法读取本地模型配置。") from None
    if value.get("n_vocab") == 51864 and config["language"] not in {"auto", "en"}:
        raise ValueError("所选权重是英语专用模型，请换用多语言 Whisper 权重；当前不会自动下载或上传音频。")
    if Path(config["model_path"]).name.endswith(".en") and config["language"] not in {"auto", "en"}:
        raise ValueError("所选权重是英语专用模型，请换用多语言 Whisper 权重。")
    if value.get("n_vocab") == 51865 and (config["language"] == "yue" or "yue" in candidates(config["language"])):
        raise ValueError("所选模型没有独立粤语语言标记，请更换支持该标记的多语言模型，或导入其他工具的转写稿。不会自动上传。")
