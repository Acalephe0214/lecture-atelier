"""Explicit, one-way Notion page export. No automatic uploads or write retries."""
import json
import re
import threading
from urllib import request, error
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from .delivery import sections
from .pipeline import _NoRedirect

API = "https://api.notion.com/v1"
VERSION = "2025-09-03"
_write_lock = threading.Lock()


def page_id(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("请填写 Notion 目标父页面的链接或 ID。")
    if value.startswith("https://"):
        parsed = urlsplit(value)
        if not (parsed.hostname in {"notion.so", "www.notion.so"} or (parsed.hostname or "").endswith(".notion.site")):
            raise ValueError("目标必须是 notion.so / notion.site 页面链接或页面 ID。")
        value = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    match = re.search(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$", value.strip())
    if not match:
        raise ValueError("没有识别到 Notion 页面 ID。请复制父页面的完整链接。")
    return str(UUID(match.group(1)))


def configuration(value):
    if not isinstance(value, dict):
        raise ValueError("Notion 配置须为对象。")
    parent = value.get("parent_page_id", "")
    if not isinstance(parent, str):
        raise ValueError("Notion 父页面须为链接或 ID。")
    parent = parent.strip()
    token = value.get("token", "")
    if not isinstance(token, str) or len(token) > 4096 or any(c in token for c in "\r\n\0"):
        raise ValueError("Notion token 格式无效。")
    return {"parent_page_id": page_id(parent) if parent else "", "token": token.strip()}


def blocks(item, english=False):
    result = []
    for kind, value in sections(item, english):
        kind = {"h1": "heading_1", "h2": "heading_2", "h3": "heading_3", "quote": "quote"}.get(kind, "paragraph")
        # UTF-16 conservative split: astral characters count twice at Notion.
        for start in range(0, max(1, len(value)), 30000):
            part = value[start:start+30000]
            rich = [{"type": "text", "text": {"content": part[pos:pos+900]}} for pos in range(0, len(part), 900)]
            result.append({"object": "block", "type": kind, kind: {"rich_text": rich}})
    return result


def batches(rows):
    current = []
    for row in rows:
        if current and (len(current) >= 80 or len(json.dumps(current + [row], ensure_ascii=False).encode()) > 300000):
            yield current
            current = []
        current.append(row)
    if current:
        yield current


def preview(item, config, english=False):
    parent = page_id(config.get("parent_page_id", ""))
    rows = blocks(item, english)
    return {"parent_page_id": parent, "title": item.get("title", ""), "blocks": len(rows),
            "requests": len(list(batches(rows))) + 1, "has_token": bool(config.get("token")),
            "contains_audio": False, "contains_full_transcript": False}


def _request(method, path, payload, token):
    req = request.Request(API + path, data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "Notion-Version": VERSION}, method=method)
    try:
        with request.build_opener(_NoRedirect()).open(req, timeout=45) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Notion 返回过大的响应，请在 Notion 中检查页面后再操作。")
        return json.loads(raw)
    except error.HTTPError as exc:
        status = exc.code
        exc.close()
        if status in {401, 403, 404}:
            raise ValueError("Notion 鉴权或页面权限不足。请检查 connection token，并将父页面连接到该 integration；未自动重试。") from None
        if status in {429, 529}:
            raise ValueError("Notion 限流或过载，已停止发送；请先检查目标页面，未自动重试写入。") from None
        raise ValueError("Notion 写入未确认（HTTP " + str(status) + "）。请在 Notion 检查实际结果，不要直接重复导出。") from None
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Notion"):
            raise
        raise ValueError("Notion 响应未确认。写入可能已成功，请在 Notion 检查，不要直接重复导出。") from None


def export(store, identity, body):
    if body.get("allow_external") is not True:
        raise ValueError("请先确认将笔记发送到 Notion。")
    config = store.private_settings().get("notion", {})
    parent = page_id(config.get("parent_page_id", ""))
    if body.get("parent_page_id") != parent or not config.get("token"):
        raise ValueError("Notion 目标已改变或 token 未配置；请重新预览。")
    if not _write_lock.acquire(blocking=False):
        raise ValueError("已有 Notion 导出正在进行，请勿重复提交。")
    attempt = {"id": uuid4().hex, "status": "sending", "parent_page_id": parent, "sent_blocks": 0}
    try:
        item = store.public_lecture(store.get(identity))
        previous = item.get("notion_export", {})
        if previous.get("status") in {"sending", "unknown"} and body.get("acknowledge_previous") != previous.get("id"):
            raise ValueError("上次 Notion 写入状态未确认，请先在 Notion 检查页面；如确需另建页面，请明确确认上次记录。")
        rows = blocks(item, body.get("ui") == "en")
        store.mutate(identity, lambda row: row.update(notion_export=dict(attempt)))
        # Create an empty child page first, so a later partial failure has a
        # recoverable URL. Never retry a timeout or non-idempotent POST/PATCH.
        created = _request("POST", "/pages", {"parent": {"type": "page_id", "page_id": parent},
            "properties": {"title": {"type": "title", "title": [{"type": "text", "text": {"content": item.get("title", "Lecture Atelier")[:900]}}]}}}, config["token"])
        identity_remote = str(UUID(created["id"]))
        attempt.update(page_id=identity_remote, url="https://www.notion.so/" + identity_remote.replace("-", ""))
        store.mutate(identity, lambda row: row.update(notion_export=dict(attempt)))
        for batch in batches(rows):
            _request("PATCH", "/blocks/" + identity_remote + "/children", {"children": batch}, config["token"])
            attempt["sent_blocks"] += len(batch)
            store.mutate(identity, lambda row: row.update(notion_export=dict(attempt)))
        attempt["status"] = "completed"
        store.mutate(identity, lambda row: row.update(notion_export=dict(attempt)))
        return attempt
    except Exception as exc:
        if attempt.get("page_id") or store.get(identity).get("notion_export", {}).get("id") == attempt["id"]:
            attempt["status"] = "unknown"
            store.mutate(identity, lambda row: row.update(notion_export=dict(attempt)))
        hint = (" 可检查页面：" + attempt["url"]) if attempt.get("url") else ""
        if isinstance(exc, ValueError):
            raise ValueError(str(exc) + hint) from None
        raise ValueError("Notion 导出未完成，请先检查目标页面。" + hint) from None
    finally:
        _write_lock.release()
