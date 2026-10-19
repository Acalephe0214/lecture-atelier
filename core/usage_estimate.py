"""Offline character-based planning ranges; never a tokenizer or billing meter."""
import json
import math
from urllib.parse import urlsplit

AS_OF = "2026-10-18"
PRICE_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"


def rates(settings):
    llm = settings.get("llm", {})
    custom = settings.get("billing", {})
    if custom.get("model") == llm.get("model") and custom.get("base_url") == llm.get("base_url") and custom.get("enabled"):
        return {**custom, "source": "manual", "as_of": custom.get("as_of", AS_OF)}
    if urlsplit(llm.get("base_url", "")).hostname == "api.deepseek.com":
        prices = {"deepseek-flash": (.15, .30, .60, 1.20), "deepseek-v4-pro": (.66, 1.32, 1.98, 3.96)}
        if llm.get("model") in prices:
            a, b, c, d = prices[llm["model"]]
            return {"input_low": a, "input_high": b, "output_low": c, "output_high": d,
                    "currency": "USD", "as_of": AS_OF, "source": PRICE_SOURCE}
    return None


def token_range(text):
    # Includes punctuation/whitespace and mixed-language material. This is not
    # model-specific tokenization. Actual usage may lie outside this interval.
    east = sum(1 for char in text if '\u2e80' <= char <= '\u9fff' or '\uf900' <= char <= '\ufaff')
    rest = len(text) - east
    return [math.ceil(east * .7 + rest * .22), math.ceil(east * 1.6 + rest * .60)]


def estimate(item, settings, scope="all", complexity="standard"):
    if not isinstance(scope,str) or not isinstance(complexity,str) or scope not in {"all", "overview", "proofreading"} or complexity not in {"light", "standard", "deep"}:
        raise ValueError("无效的用量预估选项。")
    from . import overview, workflow, pipeline
    segments = item.get("segments", [])
    raw_chars = sum(len(row.get("text", "")) for row in segments)
    result = {"model":settings.get("llm",{}).get("model",""), "source_chars":raw_chars, "scope":scope,
        "complexity":complexity,"input_tokens":[0,0],"output_tokens":[0,0],"total_tokens":[0,0],"requests":[0,0],"price":None,
        "method":"shared-payload-character-range-v2","not_a_cap":True,"can_run":bool(segments),"stages":[],"warnings":[]}
    if not segments: return result
    config = workflow.normalize(item.get("workflow"))
    scene = config["scene"]
    result["scene"] = scene
    factor = {"light": .65, "standard": 1, "deep": 1.65}[complexity] * {"class": 1.1, "lecture": .85, "discussion": 1.4, "meeting": 1.2, "custom": 1.4}.get(scene, 1)
    inp, out, requests = [0,0], [0,0], [0,0]

    def add_stage(name, inputs, outputs, calls):
        result["stages"].append({"name":name,"input_tokens":inputs,"output_tokens":outputs,"requests":calls})
        for index in (0,1):
            inp[index] += inputs[index];out[index] += outputs[index];requests[index] += calls[index]

    def message_range(body):
        value=token_range(json.dumps(body["messages"],ensure_ascii=False))
        return [number+4*len(body["messages"])+8 for number in value]

    def output_range(material, overview_output=False):
        tokens=token_range(json.dumps(material,ensure_ascii=False))
        low=min(12000,math.ceil(max(180,tokens[0]*(.04 if overview_output else .22))*factor))
        high=min(12000,max(low,math.ceil(max(650,tokens[1]*(.30 if overview_output else .9))*factor)))
        return [low,high]

    try:
        if scope in {"all","proofreading"}:
            batches=pipeline._batches(segments)
            glossary=settings.get("glossary",[])
            if not isinstance(glossary,list) or len(glossary)>300 or len(json.dumps(glossary,ensure_ascii=False))>20000:
                raise pipeline.PipelineError("术语表过大或格式无效，请缩短后重试。")
            inputs,outputs=[0,0],[0,0]
            for batch in batches:
                if scope=="proofreading":
                    from .redline import context
                    body={"messages":[{"role":"system","content":workflow.CORRECTION_PROMPT},
                        {"role":"user","content":json.dumps({"segments":batch,"glossary":glossary,"topic_context":context(item.get("proofreading_context",{}))},ensure_ascii=False)}]}
                else: body=pipeline.notes_payload(batch,glossary,config,result["model"])
                a,b=message_range(body),output_range(batch)
                for index in (0,1):inputs[index]+=a[index];outputs[index]+=b[index]
            add_stage("proofreading" if scope=="proofreading" else "details",inputs,outputs,[len(batches),len(batches)])
        if scope!="proofreading":
            notes=item.get("notes",[])
            if scope=="overview" and not notes:
                raise pipeline.PipelineError("请先准备原文和需要综合的笔记。")
            # Regenerated detail text is unknowable before a model call. Use the
            # current notes as an explicit reference, never pretend they are the
            # future response or clamp one task's totals against another.
            basis="current_notes_reference" if notes else "source_reference"
            try:
                planned=overview.plan(notes or pipeline.extract_local_notes(segments)["notes"],segments)
                overview.check_plan(planned)
            except pipeline.PipelineError:
                if scope!="all":raise
                basis="source_reference"
                planned=overview.plan(pipeline.extract_local_notes(segments)["notes"],segments)
                overview.check_plan(planned)
            groups=planned["groups"];count=len(groups)
            inputs,outputs=[0,0],[0,0]
            for group in groups:
                a=message_range(overview.payload(group,config,result["model"],count>1));b=output_range(group,True)
                for index in (0,1):inputs[index]+=a[index];outputs[index]+=b[index]
            calls=[planned["minimum_calls"],1 if count==1 else min(overview.MAX_CALLS,count*2+1)]
            if count>1:
                # Later levels depend on model outputs. Include repeated source
                # evidence and intermediate outputs, not a fake exact schedule.
                union={"entries":[],"sources":[{key:row[key] for key in ("id","text","speaker") if key in row} for row in segments]}
                merge_input=message_range(overview.payload(union,config,result["model"]))
                merge_output=output_range(union,True)
                for index in (0,1):
                    extra=calls[index]-count
                    inputs[index]+=extra*(merge_input[index]+outputs[index])
                    outputs[index]+=extra*merge_output[index]
            add_stage("overview",inputs,outputs,calls)
            result["overview_plan"]={key:value for key,value in planned.items() if key not in {"entries","groups"}}
            result["overview_plan"].update(first_pass_groups=count,basis=basis)
            if planned["source_copy_cards"]:
                result["warnings"].append("原句复制卡片仅转为原文索引，不重复发送正文；已有笔记不会被修改。" if scope=="overview" else "预估将原句复制卡片视为原文索引，不重复计算其正文；全流程仍会重新生成详细笔记。")
            if planned["added_source_passages"]:result["warnings"].append("总览将同时读取现有笔记未引用的原文，避免只总结部分材料。")
            if scope=="all":result["warnings"].append("全流程的总览阶段参考现有笔记或原文分组；新生成的详细笔记长度未知，实际综合次数和用量可能不同。")
    except pipeline.PipelineError as exc:
        result.update(can_run=False,blocked_reason=str(exc))
        return result
    total = [inp[0] + out[0], inp[1] + out[1]]
    rate = rates(settings)
    price = None if not rate else {"currency": rate["currency"], "low": round((inp[0] * rate["input_low"] + out[0] * rate["output_low"]) / 1e6, 6),
        "high": round((inp[1] * rate["input_high"] + out[1] * rate["output_high"]) / 1e6, 6), "rates": rate}
    result.update(input_tokens=inp,output_tokens=out,total_tokens=total,requests=requests,price=price,
        caveat="估算包含再次提交原文作全局综合。不是预算上限；长推理、额外综合、模型分词、缓存和费率变化均可能使实际用量超出区间。按未命中缓存估价，不含税、汇率或平台加价。")
    return result


def validate_billing(value):
    if not isinstance(value, dict):
        raise ValueError("费率配置须为对象。")
    result = {"enabled": value.get("enabled") is True}
    for name in ("model", "base_url", "currency"):
        text = value.get(name, "")
        if not isinstance(text, str) or len(text) > 500:
            raise ValueError("费率配置格式无效。")
        result[name] = text.strip()
    if result["currency"] not in {"USD", "CNY", "EUR", "GBP"}:
        raise ValueError("请选择费用币种。")
    for key in ("input_low", "input_high", "output_low", "output_high"):
        number = value.get(key, 0)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number <= 100000:
            raise ValueError("费率须为每百万 token 的非负金额。")
        result[key] = number
    if result["input_low"] > result["input_high"] or result["output_low"] > result["output_high"]:
        raise ValueError("费率下界不能大于上界。")
    result["as_of"] = AS_OF
    return result
