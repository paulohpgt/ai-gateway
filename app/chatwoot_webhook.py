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
    """
    Valida assinatura HMAC do webhook (quando CHATWOOT_WEBHOOK_SECRET estiver configurado).
    Se não houver secret, aceita.
    """
    if not CHATWOOT_WEBHOOK_SECRET:
        return True
    if not signature:
        return False

    # Algumas instalações enviam algo como: "sha256=<hash>" ou só o hash.
    sig = signature.replace("sha256=", "").strip()
    digest = hmac.new(CHATWOOT_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig)

def _get_event_id(payload: Dict[str, Any]) -> str:
    # Preferir event_id se existir; senão combinar campos comuns
    event_id = payload.get("event") or payload.get("event_name") or payload.get("id")
    if event_id:
        return str(event_id)

    # fallback: hash do payload
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

def _is_incoming_message(payload: Dict[str, Any]) -> bool:
    """
    Filtra para processar somente mensagens "incoming" (cliente).
    O formato pode variar por versão/config; então checamos alguns padrões.
    """
    msg = payload.get("message") or payload.get("data", {}).get("message") or payload.get("payload", {}).get("message")
    if not isinstance(msg, dict):
        return False

    # Padrões comuns:
    mtype = msg.get("message_type") or msg.get("type")
    # Em muitos casos: 0=incoming, 1=outgoing (ou strings)
    if mtype in (0, "incoming", "inbound"):
        return True
    if mtype in (1, "outgoing", "outbound"):
        return False

    # fallback: se tem "sender" e sender_type/role
    sender = msg.get("sender") or {}
    sender_type = sender.get("type") or sender.get("sender_type") or sender.get("role")
    if sender_type and str(sender_type).lower() in ("agent", "bot"):
        return False

    # se não conseguiu identificar, não processa
    return False

def _dedupe_once(key: str, ttl_seconds: int = 86400) -> bool:
    """
    Retorna True se for a primeira vez (processar).
    Retorna False se já foi processado (dropar).
    """
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

    # Anti-loop / filtro: só processa incoming
    if not _is_incoming_message(payload):
        return {"ok": True, "skipped": "not_incoming"}

    # Idempotência
    event_id = _get_event_id(payload)
    dedupe_key = f"cw:event:{event_id}"
    if not _dedupe_once(dedupe_key):
        return {"ok": True, "skipped": "duplicate"}

    # Por enquanto só confirma recebimento
    # Próximo passo: buscar contexto e responder via Chatwoot API
    return {"ok": True, "processed": True, "event_id": event_id}
