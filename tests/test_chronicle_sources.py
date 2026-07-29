"""Chronicle Source Plugins: normalización por fuente para el archivo diario.

Cada plugin traduce el formato nativo de su orquestador (JSON cascade de
Antigravity, JSONL de Claude Code, SQLite de opencode) a mensajes normalizados
{role, content, timestamp}. Fixtures sintéticas: nada de tocar los datos reales.
"""

import json
import sqlite3

import pytest

from red_pill.chronicle_sources.antigravity import AntigravitySourcePlugin
from red_pill.chronicle_sources.base import discover_source_plugins
from red_pill.chronicle_sources.claude_code import ClaudeCodeSourcePlugin
from red_pill.chronicle_sources.opencode import OpencodeSourcePlugin

# ── Antigravity ──────────────────────────────────────────────────────────────


@pytest.fixture
def antigravity_dir(tmp_path, monkeypatch):
	convo_dir = tmp_path / "unencrypted"
	convo_dir.mkdir()
	(convo_dir / "cid-1.json").write_text(
		json.dumps(
			{
				"cascade_id": "cid-1",
				"step_count": 3,
				"messages": [
					{"role": "user", "content": "hola"},
					{"role": "assistant", "content": "qué tal"},
				],
			}
		),
		encoding="utf-8",
	)
	(convo_dir / "cid-2.json").write_text(json.dumps({"step_count": 7, "messages": []}), encoding="utf-8")
	monkeypatch.setattr("red_pill.core.paths.get_unencrypted_conversations_dir", lambda: convo_dir)
	return convo_dir


def test_antigravity_discover_and_load(antigravity_dir):
	plugin = AntigravitySourcePlugin()
	assert plugin.discover() == [("cid-1", 3), ("cid-2", 7)]

	messages = plugin.load("cid-1")
	assert [m["role"] for m in messages] == ["user", "assistant"]
	assert messages[0]["content"] == "hola"
	# Compat: los puntos históricos usan el cascade_id desnudo — sin prefijo
	assert plugin.qualify("cid-1") == "cid-1"


def test_antigravity_missing_dir_discovers_nothing(tmp_path, monkeypatch):
	monkeypatch.setattr("red_pill.core.paths.get_unencrypted_conversations_dir", lambda: tmp_path / "nope")
	assert AntigravitySourcePlugin().discover() == []


# ── Claude Code ──────────────────────────────────────────────────────────────


@pytest.fixture
def claude_code_dir(tmp_path):
	proj = tmp_path / "projects" / "-home-joan-Workspace"
	proj.mkdir(parents=True)
	records = [
		# Ruido de harness: sin type user/assistant, se ignora
		{"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-07-28T19:45:11.962Z"},
		{
			"type": "user",
			"isSidechain": False,
			"timestamp": "2026-07-28T19:45:12.031Z",
			"message": {"role": "user", "content": "arregla el bug del registro"},
		},
		{
			"type": "assistant",
			"isSidechain": False,
			"timestamp": "2026-07-28T19:45:20.000Z",
			"message": {
				"role": "assistant",
				"content": [
					{"type": "text", "text": "Voy a mirar el fichero."},
					{"type": "tool_use", "name": "Read", "input": {"file_path": "/repo/registry.py"}},
				],
			},
		},
		# Resultado de tool en turno user: entra compactado, no verbatim
		{
			"type": "user",
			"isSidechain": False,
			"timestamp": "2026-07-28T19:45:25.000Z",
			"message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "def load():\n" + "x = 1\n" * 200}]},
		},
		# Sidechain (subagente): fuera de la cadena principal
		{"type": "user", "isSidechain": True, "timestamp": "2026-07-28T19:46:00.000Z", "message": {"role": "user", "content": "prompt de subagente"}},
		{
			"type": "user",
			"isSidechain": False,
			"isMeta": True,
			"timestamp": "2026-07-28T19:46:01.000Z",
			"message": {"role": "user", "content": "caveat interno"},
		},
	]
	transcript = proj / "d3ed8084-8f85-47a4-934b-3154747bdc09.jsonl"
	transcript.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
	return tmp_path / "projects"


def test_claude_code_discover_counts_records(claude_code_dir):
	plugin = ClaudeCodeSourcePlugin(base_dir=claude_code_dir)
	assert plugin.discover() == [("d3ed8084-8f85-47a4-934b-3154747bdc09", 6)]


def test_claude_code_load_normalizes_and_filters_noise(claude_code_dir):
	plugin = ClaudeCodeSourcePlugin(base_dir=claude_code_dir)
	messages = plugin.load("d3ed8084-8f85-47a4-934b-3154747bdc09")

	assert [m["role"] for m in messages] == ["user", "assistant", "user"]
	assert messages[0]["content"] == "arregla el bug del registro"
	assert messages[0]["timestamp"] == "2026-07-28T19:45:12.031Z"

	# El tool_use del assistant entra como marcador compacto, no como JSON verbatim
	assert "Voy a mirar el fichero." in messages[1]["content"]
	assert "[TOOL: Read file_path=/repo/registry.py]" in messages[1]["content"]

	# El tool_result masivo se compacta (cabeza + omitidos), sin el cuerpo entero
	assert messages[2]["content"].startswith("[TOOL RESULT:")
	assert "chars omitted" in messages[2]["content"]
	assert len(messages[2]["content"]) < 300

	# Namespacing: la clave lógica no colisiona con los cascade_id de Antigravity
	assert plugin.qualify("abc") == "claude_code:abc"


def test_claude_code_load_survives_partial_trailing_line(claude_code_dir):
	"""Una sesión viva puede dejar la última línea a medio escribir: se ignora."""
	transcript = claude_code_dir / "-home-joan-Workspace" / "d3ed8084-8f85-47a4-934b-3154747bdc09.jsonl"
	with open(transcript, "a", encoding="utf-8") as f:
		f.write('{"type": "user", "message": {"content": "trunca')

	plugin = ClaudeCodeSourcePlugin(base_dir=claude_code_dir)
	messages = plugin.load("d3ed8084-8f85-47a4-934b-3154747bdc09")
	assert len(messages) == 3


def test_claude_code_missing_dir_discovers_nothing(tmp_path):
	assert ClaudeCodeSourcePlugin(base_dir=tmp_path / "nope").discover() == []


# ── opencode ─────────────────────────────────────────────────────────────────


@pytest.fixture
def opencode_db(tmp_path):
	db_path = tmp_path / "opencode.db"
	con = sqlite3.connect(db_path)
	con.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT)")
	con.execute("CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT)")

	def add_message(mid, sid, t, role):
		con.execute(
			"INSERT INTO message VALUES (?, ?, ?, ?, ?)",
			(mid, sid, t, t, json.dumps({"role": role, "time": {"created": t}})),
		)

	def add_part(pid, mid, sid, t, data):
		con.execute("INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)", (pid, mid, sid, t, t, json.dumps(data)))

	add_message("m1", "ses_1", 1784544151000, "user")
	add_part("p1", "m1", "ses_1", 1784544151000, {"type": "text", "text": "configura el ancla"})
	add_message("m2", "ses_1", 1784544160000, "assistant")
	add_part("p2", "m2", "ses_1", 1784544160000, {"type": "step-start"})
	add_part("p3", "m2", "ses_1", 1784544160001, {"type": "reasoning", "text": "pensando..."})
	add_part("p4", "m2", "ses_1", 1784544160002, {"type": "text", "text": "Voy a leer la skill."})
	add_part(
		"p5",
		"m2",
		"ses_1",
		1784544160003,
		{
			"type": "tool",
			"tool": "read",
			"callID": "c1",
			"state": {"status": "completed", "input": {"path": "/repo/anchor.md"}, "output": "x" * 5000},
		},
	)
	add_part("p6", "m2", "ses_1", 1784544160004, {"type": "step-finish", "reason": "stop", "tokens": {}})
	# Mensaje sin partes con narrativa: no debe emitirse
	add_message("m3", "ses_1", 1784544170000, "assistant")
	add_part("p7", "m3", "ses_1", 1784544170000, {"type": "step-start"})
	# Segunda sesión
	add_message("m4", "ses_2", 1784544180000, "user")
	add_part("p8", "m4", "ses_2", 1784544180000, {"type": "text", "text": "hola"})

	con.commit()
	con.close()
	return db_path


def test_opencode_discover_counts_messages(opencode_db):
	plugin = OpencodeSourcePlugin(db_path=opencode_db)
	assert plugin.discover() == [("ses_1", 3), ("ses_2", 1)]


def test_opencode_load_normalizes_parts(opencode_db):
	plugin = OpencodeSourcePlugin(db_path=opencode_db)
	messages = plugin.load("ses_1")

	assert [m["role"] for m in messages] == ["user", "assistant"]
	assert messages[0]["content"] == "configura el ancla"
	assert messages[0]["timestamp"] == pytest.approx(1784544151.0)  # epoch ms → s

	# text + tool compactado; reasoning/step-* fuera
	assert "Voy a leer la skill." in messages[1]["content"]
	assert "[TOOL: read path=/repo/anchor.md]" in messages[1]["content"]
	assert "pensando" not in messages[1]["content"]
	assert "x" * 100 not in messages[1]["content"]  # el output del tool no viaja

	assert plugin.qualify("ses_1") == "opencode:ses_1"


def test_opencode_missing_db_discovers_nothing(tmp_path):
	assert OpencodeSourcePlugin(db_path=tmp_path / "nope.db").discover() == []


# ── Descubrimiento ───────────────────────────────────────────────────────────


def test_discovery_finds_all_builtin_sources():
	plugins = discover_source_plugins(only_enabled=False)
	assert [p.name for p in plugins] == ["antigravity", "claude_code", "opencode"]


def test_discovery_respects_config_gating(monkeypatch):
	import red_pill.config as cfg

	# Un global del módulo eclipsa al __getattr__ que delega en el singleton
	monkeypatch.setattr(cfg, "CHRONICLE_ARCHIVE_SOURCES", ["antigravity"], raising=False)
	plugins = discover_source_plugins()
	assert [p.name for p in plugins] == ["antigravity"]
