import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

import redis
from fastapi import APIRouter, Header, Request

from app.settings import CHATWOOT_WEBHOOK_SECRET, REDIS_URL

router = APIRouter()
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _hmac_ok(raw_body: bytes, signature: Optional[str]) -> bool:
    if not CHATWOOT_WEBHOOK_SECRET:
        return True
    if not signature:
        return False

    sig = signature.replace("sha256=", "").strip()
    digest = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig)


def _get_message_dict(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    msg = payload.get("message") or payload.get("data", {}).get("message") or payload.get("payload", {}).get("message")
    return msg if isinstance(msg, dict) else None


def _get_event_id(payload: Dict[str, Any]) -> str:
    """
    Idempotência robusta:
    1) message.id (melhor)
    2) message.message_id (fallback)
    3) conversation_id + hash do conteúdo
    4) event/id genérico
    5) hash do payload
    """
    msg = _get_message_dict(payload)
    if msg:
        mid = msg.get("id") or msg.get("message_id")
        if mid is not None:
            return f"msg:{mid}"

        cid = msg.get("conversation_id")
        if cid is not None:
            content = str(msg.get("content", ""))
            return "conv:" + str(cid) + ":" + hashlib.sha256(content.encode()).hexdigest()

    for k in ("event_id", "event", "event_name", "id"):
        if payload.get(k) is not None:
            return "evt:" + str(payload.get(k))

    return "payload:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _is_incoming_message(payload: Dict[str, Any]) -> bool:
    msg = _get_message_dict(payload)
    if not msg:
        return False

    mtype = msg.get("message_type") or msg.get("type")
    if mtype in (0, "incoming", "inbound"):
        return True
    if mtype in (1, "outgoing", "outbound"):
        return False

    sender = msg.get("sender") or {}
    sender_type = sender.get("type") or sender.get("sender_type") or sender.get("role")
    if sender_type and str(sender_type).lower() in ("agent", "bot"):
        return False

    return False


def _dedupe_once(key: str, ttl_seconds: int = 86400) -> bool:
    return r.set(name=key, value=str(int(time.time())), nx=True, ex=ttl_seconds) is True


@router.post("/webhooks/chatwoot")
async def chatwoot_webhook(
    request: Request,
    x_chatwoot_signature: Optional[str] = Header(default=None),
):
    raw = await request.body()

    if not _hmac_ok(raw, x_chatwoot_signature):
        return {"ok": False, "error": "invalid_signature"}

    try:
        payload = await request.json()
    except Exception:
        return {"ok": False, "error": "invalid_json"}

    if not _is_incoming_message(payload):
        return {"ok": True, "skipped": "not_incoming"}

    event_id = _get_event_id(payload)
    dedupe_key = f"cw:{event_id}"
    if not _dedupe_once(dedupe_key):
        return {"ok": True, "skipped": "duplicate", "event_id": event_id}

    return {"ok": True, "processed": True, "event_id": event_id}
