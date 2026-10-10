"""Test conductual del plugin de opencode (`seeds/opencode/plugins/redpill-scribe.js`).

El plugin es un artefacto JS que se despliega con placeholders sustituidos; no
tenía ninguna prueba automática (solo `node --check`). Aquí se sustituyen los
placeholders a rutas temporales, se carga el plugin REAL en `bun` y se ejercitan
sus hooks (`server()` → `chat.message` + `event`) contra una cola temporal:

- captura el turno con `originator` COMPUESTO (`opencode:<session_id>`) + `content_hash`;
- escribe el bridge del arnés (`opencode_session.json`) con session_id + workdir;
- NO escribe el bridge para sub-sesiones (`task`, con parentID).

Se omite si `bun` no está disponible.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED = REPO_ROOT / "seeds" / "opencode" / "plugins" / "redpill-scribe.js"

pytestmark = pytest.mark.skipif(shutil.which("bun") is None, reason="bun no disponible")

_QUEUE_DDL = """
CREATE TABLE memory_queue (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	prompt TEXT NOT NULL, response TEXT NOT NULL, role TEXT NOT NULL,
	status TEXT DEFAULT 'pending', created_at REAL, category TEXT DEFAULT 'mixed',
	originator TEXT, model TEXT, content_hash TEXT, session_id TEXT, affinity TEXT
)
"""

_HARNESS = """
import { Database } from "bun:sqlite";
import { readFileSync, existsSync } from "node:fs";

const plugin = (await import(process.env.PLUGIN_PATH)).default;
const hooks = await plugin.server({ directory: "/ws/proj" });

await hooks["chat.message"]({ sessionID: "s1" }, { parts: [{ type: "text", text: "hola mundo desde opencode" }] });
await hooks.event({ event: { type: "session.idle", properties: { sessionID: "s1" } } });

// Sub-sesión (parentID): NO debe pisar el bridge del padre.
await hooks.event({ event: { type: "session.created", properties: { info: { id: "child1", parentID: "s1" } } } });
await hooks["chat.message"]({ sessionID: "child1" }, { parts: [{ type: "text", text: "subtarea del panel" }] });

const db = new Database(process.env.QUEUE_DB);
const row = db.query("SELECT originator, session_id, content_hash FROM memory_queue ORDER BY id DESC LIMIT 1").get();
db.close();
const bp = `${process.env.STATE_DIR}/opencode_session.json`;
const bridge = existsSync(bp) ? JSON.parse(readFileSync(bp, "utf8")) : null;
console.log(JSON.stringify({ row, bridge }));
"""


def _run_plugin(tmp_path: Path) -> dict:
	state = tmp_path / "state"
	state.mkdir()
	queue_db = tmp_path / "bunker_queue.db"
	conn = sqlite3.connect(str(queue_db))
	conn.executescript(_QUEUE_DDL)
	conn.commit()
	conn.close()

	plugin = tmp_path / "redpill-scribe.js"
	src = SEED.read_text(encoding="utf-8")
	src = src.replace("${QUEUE_DB}", str(queue_db)).replace("${STATE_DIR}", str(state))
	plugin.write_text(src, encoding="utf-8")

	harness = tmp_path / "harness.mjs"
	harness.write_text(_HARNESS, encoding="utf-8")

	res = subprocess.run(
		["bun", str(harness)],
		capture_output=True,
		text=True,
		env={**os.environ, "PLUGIN_PATH": str(plugin), "QUEUE_DB": str(queue_db), "STATE_DIR": str(state)},
		timeout=60,
	)
	assert res.returncode == 0, f"bun falló:\n{res.stdout}\n{res.stderr}"
	return json.loads(res.stdout.strip().splitlines()[-1])


def test_plugin_captura_turno_con_originator_compuesto(tmp_path):
	out = _run_plugin(tmp_path)
	row = out["row"]
	assert row is not None
	assert row["originator"] == "opencode:s1"  # cuerpo compuesto, no "opencode" desnudo
	assert row["session_id"] == "s1"
	assert row["content_hash"], "content_hash ausente (dedup ciega del worker)"


def test_plugin_escribe_bridge_con_workdir(tmp_path):
	out = _run_plugin(tmp_path)
	bridge = out["bridge"]
	assert bridge is not None, "el bridge del arnés no se escribió"
	assert bridge["provider"] == "opencode"
	assert bridge["session_id"] == "s1"
	assert bridge["workdir"] == "/ws/proj"
	assert bridge["updated_at"] > 0


def test_plugin_no_pisa_bridge_con_subsession(tmp_path):
	out = _run_plugin(tmp_path)
	# Tras la sub-sesión child1, el bridge debe seguir siendo el del padre s1.
	assert out["bridge"]["session_id"] == "s1"
