"""Memento sabe qué modelo habló en cada sesión (2026-11-23).

opencode v2 guarda el modelo en cada mensaje del asistente, pero el puente v2 → v1
sólo copiaba rol y hora: ni `raw.json` ni `meta.json` decían si la sesión corrió
sobre DeepSeek, Opus o un local. El recuento va a `meta.json`, al registro y a la
fila del índice; NUNCA a la cabecera de `index.md` (desplazaría los rangos `#lA-B`).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

from red_pill.chronicle_sources.base import ChronicleSourcePlugin
from red_pill.chronicle_sources.opencode import OpencodeSourcePlugin
from red_pill.memento.indexes import _entry_line

REPO_ROOT = Path(__file__).resolve().parents[1]


def _assistant(text: str, model: dict | None) -> str:
	data: dict = {"content": [{"type": "text", "text": text}]}
	if model is not None:
		data["model"] = model
	return json.dumps(data)


def _db(tmp_path: Path, assistants: list[dict | None]) -> Path:
	path = tmp_path / "opencode.db"
	con = sqlite3.connect(path)
	con.execute("CREATE TABLE session_message (id TEXT, session_id TEXT, type TEXT, seq INT, time_created INT, time_updated INT, data TEXT)")
	rows = [("u0", "ses", "user", 0, 1_800_000_000_000, 0, json.dumps({"text": "hola"}))]
	for i, model in enumerate(assistants, start=1):
		rows.append((f"a{i}", "ses", "assistant", i, 1_800_000_000_000 + i, 0, _assistant(f"r{i}", model)))
	con.executemany("INSERT INTO session_message VALUES (?,?,?,?,?,?,?)", rows)
	con.commit()
	con.close()
	return path


DEEPSEEK = {"id": "deepseek-v4.1-flash", "providerID": "opencode-go", "variant": "high"}
LOCAL = {"id": "qwen3.5-9b", "providerID": "llama", "variant": "default"}


def test_opencode_v2_cuenta_los_modelos_aunque_cambien_a_mitad(tmp_path):
	plugin = OpencodeSourcePlugin(db_path=_db(tmp_path, [DEEPSEEK, DEEPSEEK, LOCAL, None]))
	assert plugin.models_of("ses") == {"deepseek-v4.1-flash": 2, "qwen3.5-9b": 1}


def test_el_raw_de_opencode_v2_conserva_modelo_proveedor_y_variante(tmp_path):
	plugin = OpencodeSourcePlugin(db_path=_db(tmp_path, [DEEPSEEK]))
	raw = json.loads(plugin.export_raw("ses", tmp_path).read_text(encoding="utf-8"))
	meta = json.loads(raw["message_rows"][1][1])
	assert (meta["modelID"], meta["providerID"], meta["variant"]) == ("deepseek-v4.1-flash", "opencode-go", "high")
	assert [m["content"] for m in plugin.load_raw(tmp_path / "raw.json")] == ["hola", "r1"]


class _SinModelo(ChronicleSourcePlugin):
	name = "sin_modelo"

	def discover(self):
		return []

	def load(self, conversation_id):
		return [{"role": "assistant", "content": "hola", "timestamp": 0}]


def test_una_fuente_que_no_sabe_el_modelo_devuelve_vacio():
	assert _SinModelo().models_of("x") == {}


class _ConSinteticos(_SinModelo):
	def load_canonical(self, conversation_id):
		return [{"role": "assistant", "model": m} for m in ("claude-opus-5-5", "<synthetic>", "claude-opus-5-5")]


def test_los_mensajes_sinteticos_del_arnes_no_cuentan_como_modelo():
	assert _ConSinteticos().models_of("x") == {"claude-opus-5-5": 2}


def test_la_fila_del_indice_dice_quien_hablo():
	entry = {"created_at": "2026-11-21T20:37:26Z", "dir": "2026-11/opencode/s", "message_count": 83, "models": {"deepseek-v4.1-flash": 57}}
	assert "· 83 msgs · deepseek-v4.1-flash" in _entry_line("opencode:s", entry, "../")
	assert "msgs ·" not in _entry_line("opencode:s", {**entry, "models": {}}, "../")


def test_meta_json_lleva_el_recuento(tmp_path):
	spec = importlib.util.spec_from_file_location("memento_migrate_models", REPO_ROOT / "scripts" / "memento_migrate.py")
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	plugin = OpencodeSourcePlugin(db_path=_db(tmp_path, [DEEPSEEK]))
	session_dir = tmp_path / "session"
	mod._export_raw(plugin, "ses", "opencode:ses", 2, None, session_dir, "2026-11-23T00:00:00Z", {"deepseek-v4.1-flash": 1})
	meta = json.loads((session_dir / "raw" / "meta.json").read_text(encoding="utf-8"))
	assert meta["models"] == {"deepseek-v4.1-flash": 1}
