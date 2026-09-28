"""Adaptadores de payload del inbox (`core/inbox_adapters`).

Cada canal entrega su payload con su forma; el worker consume siempre el mismo
`InboxMessage`. El texto normal (no-JSON) NO debe tratarse como error.
"""

from __future__ import annotations

import json

from red_pill.core.inbox_adapters import InboxMessage, parse_payload


def test_telegram_texto_plano_sin_command():
	raw = json.dumps({"text": "[Joan] hola", "sender_id": "123", "mode": "conversational"})
	m = parse_payload("telegram", "u1", raw)
	assert m.text == "[Joan] hola"
	assert m.command is None
	assert m.mode == "conversational"
	assert m.sender_id == "123"


def test_command_directo_en_payload():
	raw = json.dumps({"command": "SWITCH_CASCADE", "index": 1})
	m = parse_payload("telegram", "u1", raw)
	assert m.command == "SWITCH_CASCADE"
	assert m.payload["index"] == 1


def test_command_embebido_en_texto_json():
	nested = {"command": "NEW_CASCADE"}
	raw = json.dumps({"text": json.dumps(nested), "sender_id": "1"})
	m = parse_payload("telegram", "u1", raw)
	assert m.command == "NEW_CASCADE"
	assert m.payload == nested


def test_texto_que_parece_json_no_rompe():
	raw = json.dumps({"text": "{esto no es json valido", "mode": "conversational"})
	m = parse_payload("telegram", "u1", raw)
	assert m.command is None
	assert m.payload["text"].startswith("{")


def test_payload_vacio_ghost():
	m = parse_payload("system", "ghost_cron", "{}")
	assert m.text == ""
	assert m.mode == "conversational"
	assert m.command is None


def test_payload_invalido_no_lanza():
	m = parse_payload("telegram", "u1", "no-json")
	assert isinstance(m, InboxMessage)
	assert m.text == ""
	assert m.command is None


def test_modo_background():
	m = parse_payload("system", "u1", json.dumps({"text": "x", "mode": "background"}))
	assert m.mode == "background"


def test_adaptador_custom_por_canal(monkeypatch):
	import red_pill.core.inbox_adapters as ia

	monkeypatch.setitem(ia._ADAPTERS, "mi-canal", lambda c, u, p: ia.InboxMessage(channel=c, channel_user_id=u, text=f"custom:{p.get('x', '')}"))
	m = parse_payload("mi-canal", "u9", json.dumps({"x": 42}))
	assert m.text == "custom:42"
