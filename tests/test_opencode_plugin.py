"""Test conductual del plugin de opencode (`seeds/opencode/plugins/redpill-scribe.js`).

El plugin es un artefacto JS que se despliega con placeholders sustituidos; no
tenía ninguna prueba automática (solo `node --check`). Aquí se sustituyen los
placeholders a rutas temporales, se carga el plugin REAL en `bun` y se ejercitan
sus hooks (`server()` → `chat.message` + `event`) contra una cola temporal:

- captura el turno con `originator` COMPUESTO (`opencode:<session_id>`) + `content_hash`;
- escribe el bridge del arnés (`opencode_session.json`) con session_id + workdir;
- NO escribe el bridge para sub-sesiones (`task`, con parentID).

Runtime: los harness `harness.mjs` importan `bun:sqlite` (API exclusiva de Bun),
así que se exige un runtime con capacidad Bun. Verificado (sonda 2026-10-28): el
arnés embebe Bun 1.4.4; el test usa el Bun del sistema (o el que fije
`REDPILL_JS_RUNTIME`). Sin runtime válido → **xfail NO silencioso** (antes un
`skip` mudo que en CI —que no instala bun— significaba cobertura cero sin avisar).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from tests._js_runtime import find_js_runtime, needs_js_runtime

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED = REPO_ROOT / "seeds" / "opencode" / "plugins" / "redpill-scribe.js"

# El harness ejercita el plugin, que usa `bun:sqlite` → se exige esa capacidad.
_BUN = find_js_runtime(require_bun_sqlite=True)
# XFAIL ruidoso SOLO en los tests que ejecutan JS. Los puramente textuales (leer
# el seed y comparar) no necesitan runtime y deben pasar siempre.
_runtime = needs_js_runtime(require_bun_sqlite=True)

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


# Dos instancias en el MISMO proceso (como la app de escritorio): si el cwd vive
# en un global, la segunda (b) pisa el de la primera (a) antes de que esta
# procese su turno. La sesión debe resolver el directorio de su instancia.
_HARNESS_MULTI = """
import { readFileSync } from "node:fs";

const plugin = (await import(process.env.PLUGIN_PATH)).default;
const a = await plugin.server({ directory: "/ws/a" });
const b = await plugin.server({ directory: "/ws/b" });

await a["chat.message"]({ sessionID: "s1" }, { parts: [{ type: "text", text: "uno" }] });
const bp = `${process.env.STATE_DIR}/opencode_session.json`;
const first = JSON.parse(readFileSync(bp, "utf8"));
await b["chat.message"]({ sessionID: "s2" }, { parts: [{ type: "text", text: "dos" }] });
const second = JSON.parse(readFileSync(bp, "utf8"));
console.log(JSON.stringify({ first, second }));
"""


def _run_plugin(tmp_path: Path, harness_src: str = _HARNESS) -> dict:
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
	harness.write_text(harness_src, encoding="utf-8")

	res = _BUN.run(
		str(harness),
		capture_output=True,
		text=True,
		env={**os.environ, "PLUGIN_PATH": str(plugin), "QUEUE_DB": str(queue_db), "STATE_DIR": str(state)},
		timeout=60,
	)
	assert res.returncode == 0, f"{_BUN.label} falló:\n{res.stdout}\n{res.stderr}"
	return json.loads(res.stdout.strip().splitlines()[-1])


@_runtime
def test_plugin_captura_turno_con_originator_compuesto(tmp_path):
	out = _run_plugin(tmp_path)
	row = out["row"]
	assert row is not None
	assert row["originator"] == "opencode:s1"  # cuerpo compuesto, no "opencode" desnudo
	assert row["session_id"] == "s1"
	assert row["content_hash"], "content_hash ausente (dedup ciega del worker)"


@_runtime
def test_plugin_escribe_bridge_con_workdir(tmp_path):
	out = _run_plugin(tmp_path)
	bridge = out["bridge"]
	assert bridge is not None, "el bridge del arnés no se escribió"
	assert bridge["provider"] == "opencode"
	assert bridge["session_id"] == "s1"
	assert bridge["workdir"] == "/ws/proj"
	assert bridge["updated_at"] > 0


@_runtime
def test_plugin_no_pisa_bridge_con_subsession(tmp_path):
	out = _run_plugin(tmp_path)
	# Tras la sub-sesión child1, el bridge debe seguir siendo el del padre s1.
	assert out["bridge"]["session_id"] == "s1"


_HARNESS_PER_SESSION = """
import { readFileSync, existsSync } from "node:fs";

const plugin = (await import(process.env.PLUGIN_PATH)).default;
const a = await plugin.server({ directory: "/ws/a" });
const b = await plugin.server({ directory: "/ws/b" });

await a["chat.message"]({ sessionID: "s1" }, { parts: [{ type: "text", text: "uno" }] });
await b["chat.message"]({ sessionID: "s2" }, { parts: [{ type: "text", text: "dos" }] });

const dir = `${process.env.STATE_DIR}/sessions/bridge`;
const readOne = (sid) => {
  const p = `${dir}/opencode__${sid}.json`;
  return existsSync(p) ? JSON.parse(readFileSync(p, "utf8")) : null;
};
console.log(JSON.stringify({ s1: readOne("s1"), s2: readOne("s2") }));
"""


@_runtime
def test_plugin_escribe_bridge_por_sesion(tmp_path):
	"""D-BRIDGE: además del global, un bridge por sesión (el proxy resuelve por cwd)."""
	out = _run_plugin(tmp_path, _HARNESS_PER_SESSION)
	assert out["s1"] is not None and out["s2"] is not None, "falta el bridge por sesión"
	assert out["s1"]["session_id"] == "s1"
	assert out["s1"]["workdir"] == "/ws/a"
	assert out["s2"]["session_id"] == "s2"
	assert out["s2"]["workdir"] == "/ws/b"


@_runtime
def test_plugin_cwd_por_instancia_no_se_pisa_entre_sesiones(tmp_path):
	out = _run_plugin(tmp_path, _HARNESS_MULTI)
	# a procesa DESPUÉS de que b haya arrancado: debe conservar /ws/a.
	assert out["first"]["workdir"] == "/ws/a"
	assert out["second"]["workdir"] == "/ws/b"


# ── Handshake gate (V2: session.hook("context") + tool.hook("execute.before")) ─
# El mecanismo por turno que en V1 no hacía falta pero que V2 sí expone: sin él,
# el "primer tool call de cada turno" dependía solo de que el modelo se acordara.
_HARNESS_HANDSHAKE = """
const plugin = (await import(process.env.PLUGIN_PATH)).default;
const sessionHooks = {};
const toolHooks = {};
const ctx = {
  session: { hook: async (name, cb) => { (sessionHooks[name] ||= []).push(cb); } },
  tool: { hook: async (name, cb) => { (toolHooks[name] ||= []).push(cb); } },
  event: { subscribe: async function* () {} },
  location: { directory: "/ws/proj" },
};
await plugin.setup(ctx);

const fire = async (hooks, name, event) => {
  for (const cb of hooks[name] || []) await cb(event);
};
const tryTool = async (sessionID, tool, input = {}) => {
  try {
    await fire(toolHooks, "execute.before", { sessionID, tool, input });
    return { status: "allowed", message: "" };
  } catch (e) {
    return { status: "refused", message: String(e.message) };
  }
};
const reminders = async (sessionID) => {
  const event = { sessionID, system: [] };
  await fire(sessionHooks, "context", event);
  return event.system;
};

const result = {};
// 1) turno nuevo: el contexto lleva recordatorio y una tool cualquiera se niega.
await fire(sessionHooks, "prompt", { sessionID: "s1", prompt: { text: "hola" } });
result.reminderBefore = (await reminders("s1")).length;
result.nonHandshakeBefore = await tryTool("s1", "RedPill-Kernel_check_parallel_sessions");
// 1b) Code Mode: `execute` (gateway) nunca se niega, porque el handshake puede ir dentro.
result.gateway = await tryTool("s1", "execute");
// 1c) Code Mode con el handshake DENTRO de `execute`: acredita el turno y la
// siguiente tool real pasa (antes se rechazaba: el gateway iba exento pero sin
// acreditar, y el IDE mostraba un ✗ tras un handshake correcto).
await fire(sessionHooks, "prompt", { sessionID: "s3", prompt: { text: "code mode" } });
result.gatewayCarriesHandshake = await tryTool("s3", "execute", {
  code: 'await tools["RedPill-Kernel"].sovereign_handshake({ user_prompt: "x" })',
});
// 1d) Forma REAL del evento: `input` vacío y el código en `args`. Con
// `event.input ?? event.args` nunca se miraba `args` y el turno no se acreditaba.
await fire(sessionHooks, "prompt", { sessionID: "s4", prompt: { text: "args" } });
result.gatewayArgs = await tryTool("s4", "execute", {});
await fire(toolHooks, "execute.before", {
  sessionID: "s4",
  tool: "execute",
  input: {},
  args: { code: 'tools["RedPill-Kernel"].sovereign_handshake({user_prompt:"y"})' },
});
result.nonHandshakeAfterGatewayArgs = await tryTool("s4", "RedPill-Kernel_check_parallel_sessions");
result.nonHandshakeAfterGateway = await tryTool("s3", "RedPill-Kernel_check_parallel_sessions");
result.reminderAfterGateway = (await reminders("s3")).length;
// 2) handshake: pasa y desbloquea el turno.
result.handshake = await tryTool("s1", "RedPill-Kernel_sovereign_handshake");
result.reminderAfter = (await reminders("s1")).length;
result.nonHandshakeAfter = await tryTool("s1", "RedPill-Kernel_check_parallel_sessions");
// 3) turno siguiente: vuelve a exigirse.
await fire(sessionHooks, "prompt", { sessionID: "s1", prompt: { text: "otra cosa" } });
result.reminderNextTurn = (await reminders("s1")).length;
result.nonHandshakeNextTurn = await tryTool("s1", "RedPill-Kernel_check_parallel_sessions");
// 4) fail-open: tras MAX_REFUSALS el gate se abre (nunca deja la sesión sin salida).
await fire(sessionHooks, "prompt", { sessionID: "s2", prompt: { text: "x" } });
const seq = [];
for (let i = 0; i < 5; i++) seq.push(await tryTool("s2", "read"));
result.refusalSequence = seq;
console.log(JSON.stringify(result));
"""


def _run_plugin_handshake(tmp_path: Path, env_extra: dict | None = None) -> dict:
	state = tmp_path / "state"
	state.mkdir()
	plugin = tmp_path / "redpill-scribe.js"
	src = SEED.read_text(encoding="utf-8")
	src = src.replace("${QUEUE_DB}", str(tmp_path / "bunker_queue.db")).replace("${STATE_DIR}", str(state))
	plugin.write_text(src, encoding="utf-8")
	harness = tmp_path / "harness.mjs"
	harness.write_text(_HARNESS_HANDSHAKE, encoding="utf-8")
	env = {**os.environ, "PLUGIN_PATH": str(plugin), "STATE_DIR": str(state), **(env_extra or {})}
	res = _BUN.run(str(harness), capture_output=True, text=True, env=env, timeout=60)
	assert res.returncode == 0, f"bun falló:\n{res.stdout}\n{res.stderr}"
	return json.loads(res.stdout.strip().splitlines()[-1])


@_runtime
def test_handshake_gate_exige_el_handshake_cada_turno(tmp_path):
	out = _run_plugin_handshake(tmp_path)
	assert out["reminderBefore"] == 1, "el contexto del turno no lleva el recordatorio"
	assert out["nonHandshakeBefore"]["status"] == "refused", "una tool sin handshake debería negarse"
	# Code Mode envuelve el handshake: el gateway `execute` no se gatea (si no,
	# el propio handshake quedaría inalcanzable).
	assert out["gateway"]["status"] == "allowed"
	# Code Mode: el handshake dentro de `execute` acredita el turno.
	assert out["gatewayCarriesHandshake"]["status"] == "allowed"
	assert out["nonHandshakeAfterGateway"]["status"] == "allowed", (
		"el handshake dentro de execute debe acreditar el turno (evita el ✗ tras un handshake correcto)"
	)
	assert out["reminderAfterGateway"] == 0
	# Forma real del evento (código en `args`, `input` vacío).
	assert out["nonHandshakeAfterGatewayArgs"]["status"] == "allowed", (
		"el handshake en `args` (evento real) debe acreditar el turno"
	)
	assert "HANDSHAKE REQUIRED" in out["nonHandshakeBefore"]["message"]
	assert out["handshake"]["status"] == "allowed"
	assert out["reminderAfter"] == 0, "tras el handshake no debe repetirse el recordatorio"
	assert out["nonHandshakeAfter"]["status"] == "allowed"
	# El turno siguiente vuelve a exigirlo: no es un "una vez por sesión".
	assert out["reminderNextTurn"] == 1
	assert out["nonHandshakeNextTurn"]["status"] == "refused"
	# Fail-open: 3 rechazos y después deja pasar (kernel caído / nombre distinto).
	assert [r["status"] for r in out["refusalSequence"]] == [
		"refused", "refused", "refused", "allowed", "allowed",
	]


@_runtime
def test_handshake_gate_se_puede_desactivar(tmp_path):
	out = _run_plugin_handshake(tmp_path, {"REDPILL_HANDSHAKE_GATE": "off"})
	assert out["reminderBefore"] == 0
	assert out["nonHandshakeBefore"]["status"] == "allowed"


def test_recordatorio_nombra_la_forma_correcta_de_code_mode():
	"""El recordatorio debe nombrar el id REAL de la tool según el modo de exposición.

	Incidencia 2026-10-28: el recordatorio decía "(code-mode calls do not count)",
	FALSO en opencode v2 (Code Mode es el default de exposición MCP) → empujaba al
	agente a pedir `RedPill-Kernel_sovereign_handshake` directa, que en ese modo NO
	está en el catálogo ("No tool named ... is currently available"). Debe nombrar
	la forma de Code Mode y la de `codemode: false`, y NO repetir la afirmación falsa.
	"""
	text = SEED.read_text(encoding="utf-8")
	assert 'tools["RedPill-Kernel"].sovereign_handshake' in text, "falta la forma de Code Mode (default v2)"
	assert "RedPill-Kernel_sovereign_handshake" in text, "falta la forma de codemode:false (listado directo)"
	# La afirmación falsa sólo importa si está EN EL RECORDATORIO (el comentario
	# puede citarla para explicar por qué se retiró).
	reminder_block = text.split("const HANDSHAKE_REMINDER =", 1)[1].split(";", 1)[0]
	assert "code-mode calls do not count" not in reminder_block, (
		"la afirmación falsa sobre Code Mode no debe reaparecer en el recordatorio (incidente 2026-10-28)"
	)
