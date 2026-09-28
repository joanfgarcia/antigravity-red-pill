"""Telegram chronicle source: export_raw/load_raw (desbloquea la purga).

El base devolvía None para export_raw → las sesiones de Telegram no tenían
`raw/` y la verificación de cobertura abortaba por cobertura incompleta.
"""

from __future__ import annotations

import json

from red_pill.chronicle_sources.telegram import TelegramSourcePlugin


def _write_session(conv_dir, sid, steps, created="2026-09-28T10:00:00Z"):
	conv_dir.mkdir(parents=True, exist_ok=True)
	data = {
		"id": sid,
		"summary": {"createdAt": created},
		"steps": [{"intent": it, "message": {"text": tx}} for it, tx in steps],
	}
	(conv_dir / f"{sid}.json").write_text(json.dumps(data), encoding="utf-8")
	return conv_dir / f"{sid}.json"


def test_export_raw_copia_el_json_nativo(tmp_path):
	conv = tmp_path / "conversations"
	src = _write_session(conv, "s1", [("USER_MESSAGE", "hola"), ("ASSISTANT", "hey")])
	plugin = TelegramSourcePlugin(conv_dir=conv)
	dest = plugin.export_raw("s1", tmp_path / "raw")
	assert dest is not None and dest.exists()
	assert json.loads(dest.read_text(encoding="utf-8")) == json.loads(src.read_text(encoding="utf-8"))


def test_export_raw_sesion_inexistente_devuelve_none(tmp_path):
	plugin = TelegramSourcePlugin(conv_dir=tmp_path / "nope")
	assert plugin.export_raw("missing", tmp_path / "raw") is None


def test_load_raw_reenormaliza(tmp_path):
	conv = tmp_path / "conversations"
	_write_session(conv, "s2", [("USER_MESSAGE", "pregunta"), ("ASSISTANT", "respuesta")])
	plugin = TelegramSourcePlugin(conv_dir=conv)
	raw = plugin.export_raw("s2", tmp_path / "raw")
	msgs = plugin.load_raw(raw)
	assert [m["role"] for m in msgs] == ["user", "assistant"]
	assert msgs[0]["content"] == "pregunta"
	assert msgs[1]["content"] == "respuesta"


def test_load_raw_json_corrupto_devuelve_vacio(tmp_path):
	bad = tmp_path / "bad.json"
	bad.write_text("{no-json", encoding="utf-8")
	plugin = TelegramSourcePlugin(conv_dir=tmp_path)
	assert plugin.load_raw(bad) == []
