"""Bounded Chat Completions SSE reader. Never estimates or logs token usage."""
import json
import time
from urllib import error, request, parse

LIMIT = 8 * 1024 * 1024
LINE_LIMIT = 1024 * 1024
DEADLINE = 20 * 60


def read_stream(response, report, fail):
    started, size = time.monotonic(), 0
    content, reasoning_size, usage, finish = [], 0, None, None
    content_size, data, seen_done = 0, [], False

    def consume(raw):
        nonlocal usage, finish, content_size, reasoning_size, seen_done
        if raw == b"[DONE]":
            seen_done = True
            return
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            provider_error = bool(value.get("error"))
            if isinstance(value.get("usage"), dict):
                usage = value["usage"]
            choices = value.get("choices") or []
            if choices:
                choice = choices[0]
                delta = choice.get("delta") or {}
                text = delta.get("content") or ""
                reasoning = delta.get("reasoning_content") or ""
                if not isinstance(text, str) or not isinstance(reasoning, str):
                    raise ValueError()
                content.append(text)
                content_size += len(text)
                reasoning_size += len(reasoning)
                finish = choice.get("finish_reason") or finish
            event = {"output_chars": content_size, "reasoning_chars": reasoning_size, "usage": usage}
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
            raise fail("模型流不是有效的 Chat Completions 数据，未保存结果。") from None
        # fail can be a ValueError subclass. Keep this outside the parse catch
        # so a provider error does not get mislabeled as malformed SSE.
        report(event)
        if provider_error:
            raise fail("模型流返回错误，本次结果未保存；已报告的用量仍保留。")

    while not seen_done:
        if time.monotonic() - started > DEADLINE:
            raise fail("本次模型请求超过 20 分钟，已停止读取；服务商端可能仍产生费用。")
        line = response.readline(LINE_LIMIT + 1)
        size += len(line)
        if len(line) > LINE_LIMIT or size > LIMIT:
            raise fail("模型流返回内容过大，已停止读取；本次未保存。")
        if not line:
            if data:
                consume(b"\n".join(data))
            break
        line = line.rstrip(b"\r\n")
        if not line:
            if data:
                consume(b"\n".join(data))
                data = []
        elif line.startswith(b"data:"):
            data.append(line[5:].lstrip())
    if not seen_done and finish is None:
        raise fail("模型连接中断或未报告完成，本次结果未保存。")
    return {"choices": [{"finish_reason": finish, "message": {"content": "".join(content)}}], "usage": usage}


def chat(url, payload, headers, report):
    # Import lazily to reuse the same endpoint/DNS/redirect safety boundary.
    from . import pipeline
    pipeline._validate_dns(url)
    payload = dict(payload, stream=True, stream_options={"include_usage": True})
    req = request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={**headers, "Content-Type": "application/json", "Accept": "text/event-stream"}, method="POST")
    try:
        handlers = [pipeline._NoRedirect()]
        if parse.urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}:
            # Explicit loopback gateways must not go through a system HTTP proxy.
            handlers.append(request.ProxyHandler({}))
        opener = request.build_opener(*handlers)
        with opener.open(req, timeout=120) as response:
            if "text/event-stream" in response.headers.get("Content-Type", "").lower():
                return read_stream(response, report, pipeline.PipelineError)
            body = response.read(LIMIT + 1)
            if len(body) > LIMIT:
                raise pipeline.PipelineError("模型返回内容过大，本次未保存。")
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError()
            choice = (value.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content, reasoning = message.get("content"), message.get("reasoning_content")
            report({"usage": value.get("usage"), "output_chars": len(content) if isinstance(content, str) else 0, "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else 0})
            return value
    except pipeline.PipelineError:
        raise
    except error.HTTPError as exc:
        message = {401: "服务拒绝认证，请检查 API 密钥及账号权限。", 403: "服务拒绝认证，请检查 API 密钥及账号权限。", 429: "服务调用限额或频率受限，请稍后再试。", 400: "服务拒绝流式 JSON 请求，请检查接口是否兼容 stream 和 stream_options；没有自动重试。"}.get(exc.code, "服务未能完成请求，请检查配置并稍后重试。")
        raise pipeline.PipelineError(message) from None
    except (OSError, ValueError, TypeError, IndexError, AttributeError, error.URLError):
        raise pipeline.PipelineError("连接服务失败、超时或返回格式无效；本次结果未保存。") from None
