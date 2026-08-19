"""Notificaciones de Telegram al abrir/cerrar operaciones.

Efecto colateral aislado: un fallo de red o credenciales ausentes no debe
interrumpir el motor, así que ``send_telegram_message`` nunca lanza.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5


def send_telegram_message(text: str) -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS)
    except Exception:
        log.exception("No se pudo enviar notificación a Telegram")
