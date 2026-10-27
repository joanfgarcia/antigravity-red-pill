/**
 * Red Pill Scribe Plugin for OpenCode — dual entrypoint (v1 + v2)
 *
 * ── ROLE IN THE ARCHITECTURE ─────────────────────────────────────────────
 * This plugin is the RAW CAPTURE LAYER for opencode sessions. It queues
 * prompt+response pairs into bunker_queue.db's `memory_queue` via SQLite WAL.
 *
 * DATA PIPELINE (3 stages):
 *   1. THIS PLUGIN → bunker_queue.db memory_queue (raw text, this file)
 *   2. Queue Worker → interaction_memories in Qdrant (embeddings, Python)
 *   3. Sleep Cycle → social_memories / work_memories (consolidation, Python)
 *
 * Stages 2 and 3 are pure Python (red-pill kernel). This plugin only handles
 * stage 1. Do NOT add embedding, Qdrant, or consolidation logic here.
 *
 * It writes to THE queue the worker already drains. An earlier version wrote
 * to a private `interactions` table in bunker.db that no consumer ever read,
 * so every opencode turn was captured and then swept away by the janitor
 * without becoming a memory. Do not reintroduce a second sink.
 *
 * ── CONCURRENCY ──────────────────────────────────────────────────────────
 * This plugin and the Python MCP server share bunker.db via SQLite WAL mode.
 * WAL allows concurrent readers + single writer without blocking. Both sides
 * must enable WAL on connection:
 *   JS:  db.exec("PRAGMA journal_mode=WAL")
 *   Python: conn.execute("PRAGMA journal_mode=WAL")
 *
 * The schema is owned by Python (MemoryQueueManager creates and migrates it);
 * this plugin only INSERTs. It degrades to a no-op if the table is missing,
 * which happens only before the kernel has ever run.
 *
 * ── HOOK LIFECYCLE (v1 — server()) ───────────────────────────────────────
 *   chat.message         → capture user prompt
 *   message.updated      → on user: track msg ID; on assistant: track model
 *   message.part.updated → accumulate assistant response text (streaming)
 *   session.idle         → FLUSH to DB (status.idle as fallback)
 *   session.created/updated/deleted → track sub-sessions (parentID): no heartbeat
 *   dispose              → flush remaining buffers on plugin unload
 *
 * NOTE: the flush trigger is the END of the turn (session.idle, verified in
 * 1.18.32 — also fires on tool-heavy turns). Flushing on the first assistant
 * message.updated captured the message at creation time, before its text
 * parts existed → empty responses (bug fixed 2026-09-24).
 *
 * ── HOOK LIFECYCLE (v2 — setup(ctx)) ─────────────────────────────────────
 *   ctx.session.hook("prompt")      → capture user prompt + RESET del turno (handshake gate)
 *   ctx.session.hook("context")    → recordatorio del handshake en CADA petición al modelo
 *                                    (no persistido: inmune a la compactación)
 *   ctx.tool.hook("execute.before")→ GATE: niega tools hasta el handshake del turno
 *                                    (fail-open tras N rechazos, exento en sub-sesiones)
 *   session.step.started            → capture model (providerID/id)
 *   session.text.delta              → accumulate assistant response text
 *   session.execution.succeeded     → FLUSH to DB (also .failed/.interrupted)
 *   session.idle / status idle      → liveness only (never flush: can truncate)
 *   cleanup (returned)              → abort event stream + await flush + close
 *
 *   v2 context: workspace = `ctx.location.directory` (NOT `ctx.directory`);
 *   event fields live on `data` (data.sessionID/parentID/location.directory),
 *   with a `data.info` fallback for v1-style serializers.
 *   The entrypoint stays a plain object `{ id, setup }`; V2 accepts id+setup
 *   without importing @opencode/plugin, so the same file still loads on v1.
 *
 * v1 calls server(); v2 calls setup(). Both share the queue writer and the
 * per-session buffer. setup() guards on the v2 context (session.hook +
 * event.subscribe): if either is absent it no-ops, so the v1 server() hooks
 * remain the single capture path. The entrypoint is a plain object (no
 * @opencode/plugin import): the same file loads on both runtimes without npm
 * dependencies.
 *
 * ── WHY NOT CALL PYTHON DIRECTLY? ───────────────────────────────────────
 * Bun.spawn per turn adds ~50-100ms overhead. The plugin is intentionally
 * minimal: capture hooks + single INSERT. All heavy processing (embeddings,
 * Qdrant, sleep) lives in tested Python code. DRY is maintained by keeping
 * this plugin as a thin capture shim only.
 *
 * QUEUE_DB path is injected at deploy time by inject_opencode.py.
 * Runtime: Bun — uses bun:sqlite.
 */

import { mkdirSync, writeFileSync, renameSync, readFileSync, unlinkSync } from "node:fs";
import { createHash } from "node:crypto";

const QUEUE_DB = "${QUEUE_DB}";
const STATE_DIR = "${STATE_DIR}";
const ORIGINATOR = "opencode";
// El cuerpo es compuesto (`opencode:<session_id>`): identifica la sesión nativa.
// ORIGINATOR se conserva para el nombre de los ficheros de latido.
function compositeOriginator(sessionId) {
  return sessionId ? `${ORIGINATOR}:${sessionId}` : ORIGINATOR;
}
// Apaga SOLO la captura (el bridge ya relaya el turno). El latido sigue: una
// sesión sin captura (p.ej. Telegram) sigue viva y debe verse en el tablón.
const CAPTURE_DISABLED = process.env.REDPILL_SCRIBE_DISABLE === "1";

// ── SESSION LIVENESS (RFC-DESPERTAR-001, P4) ────────────────────────────────
// Touch de un fichero vacío por turno: `.start` al recibir el prompt, `.end` al
// terminar el turno. mtime = señal; el par detecta "en vuelo". Best-effort:
// nunca rompe el turno. Ver red_pill/core/session_liveness.py.
//
// Las sub-sesiones (tool `task`, paneles de subagentes: `parentID`) no laten:
// mientras corren, el turno del padre ya está en vuelo. Se conocen por los
// eventos session.created/updated (v1); si un `.start` se cuela antes del
// evento, el tablón las descarta igualmente por `parent_id` en opencode.db.
const childSessions = new Set();
// `directory` real de cada sesión (session.created/updated). Es la fuente más
// fiable: el proceso de escritorio hospeda varias instancias (incluida `/`) y
// un `harnessCwd` global acababa pisado por la última que arrancaba.
const sessionDirs = new Map();

function trackSessionInfo(event) {
  const info = event?.properties?.info;
  if (!info?.id) return;
  if (typeof info.directory === "string" && info.directory) sessionDirs.set(info.id, info.directory);
  if (event.type === "session.deleted") {
    childSessions.delete(info.id);
    sessionDirs.delete(info.id);
  } else if (info.parentID) childSessions.add(info.id);
}

// ── WRITE-AHEAD (B-01h) ─────────────────────────────────────────────────────
// Journal JSON antes del modelo; el kernel lo importa al espejo. Sin ruta a
// Python y sin schema SQL en JS: un fichero por turno, atómico.
const TURN_JOURNAL_DISABLED = process.env.REDPILL_TURN_JOURNAL_DISABLE === "1";
const TURN_ROOT = `${STATE_DIR}/external_turns`;

function safeTurn(token) {
  return String(token ?? "").replace(/[/:]/g, "_").replace(/__/g, "_");
}

function turnCurrent(sessionId) {
  return `${TURN_ROOT}/current/opencode__${safeTurn(sessionId)}.json`;
}

function turnArchive(sessionId, requestId) {
  return `${TURN_ROOT}/archive/opencode__${safeTurn(sessionId)}__${safeTurn(requestId)}.json`;
}

function writeJson(path, data) {
  const tmp = `${path}.tmp`;
  mkdirSync(path.slice(0, path.lastIndexOf("/")), { recursive: true });
  writeFileSync(tmp, JSON.stringify(data));
  renameSync(tmp, path);
}

function readJson(path) {
  try { return JSON.parse(readFileSync(path, "utf8")); } catch (_) { return null; }
}

function beginExternalTurn(sessionId, prompt, cwd) {
  if (TURN_JOURNAL_DISABLED || !sessionId || !prompt || !String(prompt).trim()) return;
  // Seed sin sustituir (deploy roto): no escribir bajo una ruta literal ${...}.
  if (String(TURN_ROOT).includes("${")) return;
  try {
    const current = turnCurrent(sessionId);
    const previous = readJson(current);
    if (previous?.status === "pending") {
      if (previous.prompt === prompt) return;
      previous.status = "aborted";
      previous.reason = "superseded";
      previous.ended_at = Date.now() / 1000;
      writeJson(turnArchive(sessionId, previous.request_id || "unknown"), previous);
    }
    const stamp = Date.now() / 1000;
    writeJson(current, {
      provider: "opencode",
      session_id: sessionId,
      originator: compositeOriginator(sessionId),
      request_id: `opencode:${sessionId}:${Date.now()}:${Math.random().toString(16).slice(2, 10)}`,
      prompt: String(prompt),
      cwd: String(cwd || ""),
      model: null,
      started_at: stamp,
      status: "pending",
    });
  } catch (_) {}
}

function finishExternalTurn(sessionId, response, status = "completed", reason = "", model = null) {
  if (TURN_JOURNAL_DISABLED || !sessionId) return;
  try {
    const current = turnCurrent(sessionId);
    const data = readJson(current);
    if (!data) return;
    data.status = status === "aborted" ? "aborted" : "completed";
    data.response = String(response || "");
    data.reason = reason || null;
    data.model = model || data.model || null;
    data.ended_at = Date.now() / 1000;
    writeJson(turnArchive(sessionId, data.request_id || "unknown"), data);
    unlinkSync(current);
  } catch (_) {}
}

function touchLiveness(sessionId, phase) {
  if (!sessionId || childSessions.has(sessionId) || !STATE_DIR || STATE_DIR.includes("${")) return;
  try {
    const safe = String(sessionId).replace(/\//g, "_").replace(/__/g, "_");
    const dir = `${STATE_DIR}/sessions/live`;
    mkdirSync(dir, { recursive: true });
    writeFileSync(`${dir}/${ORIGINATOR}__${safe}.${phase}`, "");
  } catch (_) {}
}

// ── HARNESS BRIDGE (Alma y Coro, A1/A2) ─────────────────────────────────────
// El servidor MCP corre con cwd = kernel (uv --directory ${REDPILL_DIR}), así
// que no puede derivar ni originator ni `ws:`/`repo:` del workspace del agente.
// Este fichero JSON enlaza la única verdad que el hook SÍ conoce: sessionId y
// (best-effort) cwd. `_resolve_session_identity` lo lee cuando el handshake no
// pasa originator → `opencode:<session_id>` real + rama del workspace.
const BRIDGE_PATH = `${STATE_DIR}/opencode_session.json`;

// Directorio del workspace de la instancia que sirve la sesión (v1
// PluginInput.directory / v2 ctx.location.directory). Viaja en una closure por
// instancia, NO en un global: la app de escritorio arranca varias instancias
// (`/`, `~/Documents/IA`, cada workspace) en el mismo proceso y la última pisaba
// el cwd de todas (bug destapado por B01H-CWD-CHECK).
function writeBridge(sessionId, cwdHint) {
  if (!sessionId || childSessions.has(sessionId) || !STATE_DIR || STATE_DIR.includes("${")) return;
  try {
    const payload = {
      provider: "opencode",
      session_id: String(sessionId),
      workdir: String(cwdHint || "").trim(),
      updated_at: Date.now() / 1000,
    };
    const tmp = `${BRIDGE_PATH}.${process.pid}.tmp`;
    writeFileSync(tmp, JSON.stringify(payload));
    renameSync(tmp, BRIDGE_PATH);
  } catch (_) {}
}

// v2 no expone `cwd` en los eventos de prompt/chat. Prioridad: payload del
// hook → `ctx.location.directory` (v2) → `directory` (v1) de la sesión/instancia.
// IMPORTANTE: el contrato de plugins v2 expone el workspace en
// `ctx.location.directory`, NO en `ctx.directory` (ver migración V1→V2).
function dirOf(arg) {
  const v =
    arg?.cwd ||
    arg?.workspaceDirectory ||
    arg?.workspace ||
    arg?.location?.directory ||
    arg?.directory ||
    arg?.worktree ||
    arg?.app?.path?.cwd;
  return typeof v === "string" && v ? v : "";
}

function resolveCwd(sessionId, instanceCwd, ...args) {
  for (const arg of args) {
    const v = dirOf(arg);
    if (v) return v;
  }
  const known = sessionId ? sessionDirs.get(sessionId) : "";
  return known || instanceCwd || "";
}

function hasQueue(db) {
  const row = db
    .query("SELECT name FROM sqlite_master WHERE type='table' AND name='memory_queue'")
    .get();
  return Boolean(row);
}

function queueColumns(db) {
  try {
    return new Set(db.query("PRAGMA table_info(memory_queue)").all().map((r) => r.name));
  } catch (_) {
    return new Set();
  }
}

function contentHash(a, b) {
  try {
    return createHash("sha256").update(`${a || ""}\u0000${b || ""}`).digest("hex");
  } catch (_) {
    return null;
  }
}

function writeInteraction(db, prompt, response, model, sessionId, cols) {
  if (!prompt && !response) return;
  // Full text on purpose: truncating here would silently mutilate the engram
  // downstream. Noise trimming is the worker's job, at the single drain point.
  // session_id se captura cuando el esquema lo lleva (single-writer); la afinidad
  // del cwd se retiró (AD-034). El originator es compuesto (`opencode:<session>`):
  // el tablón y Memento necesitan el cuerpo, no solo el proveedor.
  // content_hash cierra la dedup ciega del worker (las filas del hook deben
  // deduplicarse como las del relay) — mismo digest que enqueue_memory.
  const originator = compositeOriginator(sessionId);
  const hash = cols.has("content_hash") ? contentHash(prompt, response) : null;
  if (cols.has("session_id") && cols.has("affinity")) {
    if (hash) {
      const stmt = db.prepare(
        "INSERT INTO memory_queue (prompt, response, role, status, created_at, category, originator, model, session_id, affinity, content_hash) " +
          "VALUES (?, ?, 'assistant', 'pending', ?, 'mixed', ?, ?, ?, ?, ?)"
      );
      stmt.run(prompt || "", response || "", Date.now() / 1000, originator, model || null, sessionId || null, null, hash);
    } else {
      const stmt = db.prepare(
        "INSERT INTO memory_queue (prompt, response, role, status, created_at, category, originator, model, session_id, affinity) " +
          "VALUES (?, ?, 'assistant', 'pending', ?, 'mixed', ?, ?, ?, ?)"
      );
      stmt.run(prompt || "", response || "", Date.now() / 1000, originator, model || null, sessionId || null, null);
    }
  } else if (hash) {
    const stmt = db.prepare(
      "INSERT INTO memory_queue (prompt, response, role, status, created_at, category, originator, model, content_hash) " +
        "VALUES (?, ?, 'assistant', 'pending', ?, 'mixed', ?, ?, ?)"
    );
    stmt.run(prompt || "", response || "", Date.now() / 1000, originator, model || null, hash);
  } else {
    const stmt = db.prepare(
      "INSERT INTO memory_queue (prompt, response, role, status, created_at, category, originator, model) " +
        "VALUES (?, ?, 'assistant', 'pending', ?, 'mixed', ?, ?)"
    );
    stmt.run(prompt || "", response || "", Date.now() / 1000, originator, model || null);
  }
}

let storePromise = null;

// ── SQLITE BACKEND (runtime-agnostic) ───────────────────────────────────────
// Bun CLI: `bun:sqlite`. Desktop (Electron/Node): the default ESM loader
// rejects the `bun:` protocol, so the old single-backend import left desktop
// turns journaled but never queued. Fallback chain: node:sqlite (built-in),
// then better-sqlite3. All three expose prepare/exec/close; we add `query`
// (Bun style) so the rest of the writer stays unchanged.
function compatDb(raw) {
  return {
    query(sql) {
      const stmt = raw.prepare(sql);
      return {
        get: (...args) => stmt.get(...args),
        all: (...args) => stmt.all(...args),
        run: (...args) => stmt.run(...args),
      };
    },
    prepare: (sql) => raw.prepare(sql),
    exec: (sql) => raw.exec(sql),
    close: () => raw.close(),
  };
}

async function openDatabase() {
  try {
    const { Database } = await import("bun:sqlite");
    return compatDb(new Database(QUEUE_DB));
  } catch (_) {}
  try {
    const { DatabaseSync } = await import("node:sqlite");
    return compatDb(new DatabaseSync(QUEUE_DB));
  } catch (_) {}
  try {
    const { createRequire } = await import("node:module");
    const require = createRequire(import.meta.url);
    const Database = require("better-sqlite3");
    return compatDb(new Database(QUEUE_DB));
  } catch (_) {}
  return null;
}

async function initStore() {
  // Seed sin sustituir (deploy roto): no crear un fichero llamado "${QUEUE_DB}".
  if (String(QUEUE_DB).includes("${")) return null;
  try {
    const db = await openDatabase();
    if (!db) {
      console.error("[RedPillScribe] No SQLite backend (bun:sqlite/node:sqlite/better-sqlite3). Capture disabled.");
      return null;
    }
    db.exec("PRAGMA journal_mode=WAL");
    db.exec("PRAGMA busy_timeout=5000");
    if (!hasQueue(db)) {
      console.error("[RedPillScribe] memory_queue missing; run the red-pill kernel once. Capture disabled.");
      db.close();
      return null;
    }
    return { db, cols: queueColumns(db) };
  } catch (e) {
    console.error("[RedPillScribe] Failed to open the queue:", e.message);
    return null;
  }
}

function getStore() {
  if (!storePromise) storePromise = initStore();
  return storePromise;
}

function closeStore() {
  if (!storePromise) return;
  storePromise
    .then((store) => {
      try {
        store?.db?.close();
      } catch (_) {}
    })
    .catch(() => {});
  storePromise = null;
}

const sessions = new Map();

async function flushSession(sessionId, status = "completed", reason = "") {
  const state = sessions.get(sessionId);
  if (!state) return;
  if (state.idleTimer) clearTimeout(state.idleTimer);
  sessions.delete(sessionId);
  if (state.prompt) finishExternalTurn(sessionId, state.response, status, reason, state.modelID);
  if (!state.prompt && !state.response) return;
  const store = await getStore();
  if (!store) return;
  try {
    writeInteraction(store.db, state.prompt, state.response, state.modelID, sessionId, store.cols);
  } catch (e) {
    console.error("[RedPillScribe] Write failed:", e.message);
  }
}

async function handleV2Event(event) {
  const type = event?.type;
  const data = event?.data;
  if (!type) return;

  // Ciclo de vida de sesión. En v2 los campos van directamente en `data`
  // (sessionID, parentID, location.directory); algunas versiones/serializadores
  // los anidan bajo `data.info` (forma v1). Aceptamos ambas. Las sub-sesiones
  // (tool `task`, paneles de subagentes) no laten: su turno vive dentro del
  // turno del padre (paridad con trackSessionInfo del path v1).
  const info = data?.info || data || {};
  const sessionId = data?.sessionID || info?.sessionID;
  const sessionDir =
    info?.location?.directory || info?.directory || event?.location?.directory;
  const infoId = info?.id || sessionId;
  if (infoId && typeof sessionDir === "string" && sessionDir) sessionDirs.set(infoId, sessionDir);
  if (infoId && info?.parentID) childSessions.add(infoId);
  if (type === "session.deleted") {
    const deadId = info?.id || sessionId;
    if (deadId) {
      childSessions.delete(deadId);
      sessionDirs.delete(deadId);
      sessions.delete(deadId);
    }
  }

  if (!sessionId) return;

  // Fin de turno. V2 publica `session.execution.{succeeded,failed,interrupted}`
  // como eventos terminales. NO cerramos con `session.idle`: puede llegar antes
  // que los últimos deltas y truncar la respuesta (hallazgo de la auditoría
  // adversarial ronda 1). El latido sí se marca en idle/status idle.
  if (
    type === "session.execution.succeeded" ||
    type === "session.execution.failed" ||
    type === "session.execution.interrupted"
  ) {
    touchLiveness(sessionId, "end");
    const completed = type === "session.execution.succeeded";
    const reason =
      type === "session.execution.failed" ? "execution_failed"
      : type === "session.execution.interrupted" ? "interrupted" : "";
    await flushSession(sessionId, completed ? "completed" : "aborted", reason);
    return;
  }
  if (type === "session.idle" || (type === "session.status" && data?.status?.type === "idle")) {
    touchLiveness(sessionId, "end");
    // Fallback de contrato: la doc V2 muestra `session.idle` como fin de turno,
    // mientras que el paquete publica `session.execution.*`. Flush con debounce
    // (no en el acto) para que los últimos deltas lleguen; si execution.* llega,
    // lo cancela y hace el flush inmediato. Así funcionan ambos contratos sin
    // truncar respuestas.
    const state = sessions.get(sessionId);
    if (state) {
      if (state.idleTimer) clearTimeout(state.idleTimer);
      state.idleTimer = setTimeout(() => {
        void flushSession(sessionId, "completed", "idle");
      }, 750);
    }
    return;
  }

  const state = sessions.get(sessionId);
  if (!state) return;

  if (type === "session.step.started") {
    const model = data?.model || info?.model;
    if (model?.id) state.modelID = model.providerID ? `${model.providerID}/${model.id}` : model.id;
    return;
  }

  if (type === "session.text.delta") {
    const delta = data?.delta ?? info?.delta;
    if (typeof delta === "string" && delta) state.response += delta;
  }
}

export default {
  id: "redpill-scribe",

  async setup(ctx) {
    // Workspace de ESTA instancia (A2), capturado en la closure.
    const instanceCwd = dirOf(ctx);
    // Si el proceso fue lanzado por un bridge red-pill (Telegram/awakenings/
    // minions), el bridge ya relaya el turno a la cola: el plugin no captura
    // (no duplica ni guarda el prompt envuelto sin respuesta), pero sí late.
    if (typeof ctx?.session?.hook !== "function" || typeof ctx?.event?.subscribe !== "function") return;

    await ctx.session.hook("prompt", (event) => {
      const sessionId = event?.sessionID || event?.data?.sessionID;
      const text = event?.prompt?.text ?? event?.data?.prompt?.text;
      if (sessionId) {
        touchLiveness(sessionId, "start");
        writeBridge(sessionId, resolveCwd(sessionId, instanceCwd, event, event?.data));
      }
      if (sessionId && text && !CAPTURE_DISABLED) {
        beginExternalTurn(sessionId, text, resolveCwd(sessionId, instanceCwd, event, event?.data));
        const prev = sessions.get(sessionId);
        if (prev?.idleTimer) clearTimeout(prev.idleTimer);
        sessions.set(sessionId, { prompt: text, response: "", modelID: null, userMsgIDs: new Set() });
      }
    });

    // ── Handshake gate (por turno) ─────────────────────────────────────────
    // V2: `session.hook("context")` corre ANTES DE CADA petición al modelo
    // (incluido el bucle de herramientas), así que es el sitio exacto para que
    // el agente vea el recordatorio en cada turno — inmune a la compactación
    // porque no se persiste. `tool.hook("execute.before")` lo hace cumplir.
    // Exentas las sub-sesiones (`task`/paneles): su padre ya hizo el handshake.
    const HANDSHAKE_GATE = (process.env.REDPILL_HANDSHAKE_GATE || "").toLowerCase() !== "off";
    const MAX_REFUSALS = 3; // fail-open: nunca dejar una sesión sin salida
    const HANDSHAKE_REMINDER =
      "<redpill_handshake_reminder>\n" +
      "MANDATORY FIRST STEP OF THIS TURN (not done yet): call `sovereign_handshake` " +
      "(the tool whose id contains `sovereign_handshake`) with only `user_prompt`, " +
      "before calling any other tool (code-mode calls do not count). Until you do, " +
      "every other tool call is refused. " +
      "That call loads identity, pain signals and OPEN LOOPS.\n" +
      "</redpill_handshake_reminder>";
    const turnHandshake = new Map(); // sessionID -> bool
    const turnRefusals = new Map(); // sessionID -> nº de rechazos
    const turnSid = (event) => event?.sessionID || event?.data?.sessionID || "global";
    const isHandshakeTool = (name) => /sovereign_handshake/i.test(String(name || ""));
    // Code Mode: el modelo puede llamar al handshake DENTRO de `execute`, así que
    // la puerta no puede negar el gateway (perdería el propio handshake). El
    // recordatorio por `context` sigue llegando en cada petición, y las tools
    // reales de trabajo (shell/edit/write/read/task) sí quedan gateadas.
    const GATEWAY_TOOLS = new Set(["execute"]);
    // Si el handshake viaja DENTRO de `execute` (Code Mode), el turno ya cumplió.
    // Sin esto el gateway quedaba exento pero sin acreditar y la siguiente tool
    // real se rechazaba (✗ "HANDSHAKE REQUIRED" visible en el IDE tras un
    // handshake correcto).
    const mentionsHandshake = (payload) => {
      try {
        return /sovereign_handshake/i.test(JSON.stringify(payload ?? ""));
      } catch (_) {
        return false;
      }
    };

    await ctx.session.hook("prompt", (event) => {
      const sid = turnSid(event);
      turnHandshake.set(sid, false);
      turnRefusals.delete(sid);
    });

    await ctx.session.hook("context", (event) => {
      if (!HANDSHAKE_GATE) return;
      const sid = turnSid(event);
      if (childSessions.has(sid) || turnHandshake.get(sid) === true) return;
      if (Array.isArray(event?.system)) event.system.push({ type: "text", text: HANDSHAKE_REMINDER });
    });

    if (typeof ctx?.tool?.hook === "function") {
      await ctx.tool.hook("execute.before", (event) => {
        const sid = turnSid(event);
        const toolName = String(event?.tool || "").toLowerCase();
        if (isHandshakeTool(event?.tool)) {
          turnHandshake.set(sid, true);
          return;
        }
        if (GATEWAY_TOOLS.has(toolName) && mentionsHandshake(event?.input ?? event?.args)) {
          turnHandshake.set(sid, true);
          return;
        }
        if (!HANDSHAKE_GATE || childSessions.has(sid) || turnHandshake.get(sid) === true) return;
        if (GATEWAY_TOOLS.has(toolName)) return;
        const refusals = turnRefusals.get(sid) || 0;
        if (refusals >= MAX_REFUSALS) return; // kernel caído o nombre distinto: no bloquear para siempre
        turnRefusals.set(sid, refusals + 1);
        throw new Error(
          "HANDSHAKE REQUIRED: this turn has not called `sovereign_handshake` yet. " +
            "Call it first (only `user_prompt`), then repeat this tool call. " +
            `Refusal ${refusals + 1}/${MAX_REFUSALS} (after that the gate opens to avoid a deadlock).`,
        );
      });
    }

    const controller = new AbortController();
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          try {
            await handleV2Event(event);
          } catch (e) {
            console.error("[RedPillScribe] Event handling failed:", e.message);
          }
        }
      } catch (_) {
        // stream abortado (cleanup) o servidor caído: sin ruido
      }
    })();

    return async () => {
      controller.abort();
      // Esperar los flush ANTES de cerrar la DB (hallazgo adversarial ronda 1:
      // el cierre podía adelantarse a la escritura async).
      await Promise.all(Array.from(sessions.keys()).map((id) => flushSession(id)));
      closeStore();
    };
  },

  async server(input) {
    // Workspace de ESTA instancia (v1), capturado en la closure: el server MCP
    // corre con cwd=checkout del kernel, esto es lo único que ve el workspace.
    const instanceCwd = dirOf(input);
    // Sin captura no se crea state: los hooks de captura quedan inertes
    // (`!state`) y solo se marca el latido.
    return {
      dispose: async () => {
        for (const [sid, state] of sessions) {
          if (state?.prompt) {
            try {
              await flushSession(sid);
            } catch (_) {}
          }
        }
        sessions.clear();
        closeStore();
      },

      "chat.message": async (input, output) => {
        const { sessionID } = input;
        if (sessionID) {
          touchLiveness(sessionID, "start");
          writeBridge(sessionID, resolveCwd(sessionID, instanceCwd, input, output));
        }
        if (CAPTURE_DISABLED) return;
        const parts = output.parts || [];
        const textParts = parts
          .filter((p) => p.type === "text")
          .map((p) => p.text)
          .join("\n");
        if (textParts) {
          beginExternalTurn(sessionID, textParts, resolveCwd(sessionID, instanceCwd, input, output));
          sessions.set(sessionID, {
            prompt: textParts,
            response: "",
            userMsgIDs: new Set(),
            modelID: input.modelID || output.modelID || null,
          });
        }
      },

      event: async ({ event }) => {
        if (event.type === "session.created" || event.type === "session.updated" || event.type === "session.deleted") {
          trackSessionInfo(event);
          return;
        }

        if (event.type === "message.updated") {
          const msg = event.properties?.info;
          if (!msg?.sessionID) return;

          const state = sessions.get(msg.sessionID);
          if (!state) return;

          if (msg.role === "user") {
            state.userMsgIDs.add(msg.id);
            return;
          }

          if (msg.role === "assistant" && msg.modelID) {
            state.modelID = msg.modelID;
          }
          return;
        }

        if (event.type === "message.part.updated") {
          const part = event.properties?.part;
          if (!part?.sessionID) return;
          const state = sessions.get(part.sessionID);
          if (!state) return;

          if (part.type === "text" && part?.text && !state.userMsgIDs.has(part.messageID)) {
            state.response += part.text;
          }
          return;
        }

        // Fin de turno real (verificado en 1.18.32, también en turnos con
        // herramientas): idle por sesión. status.idle es el mismo cierre por
        // otra vía; flushSession es idempotente (la segunda vez no hay state).
        if (
          event.type === "session.idle" ||
          (event.type === "session.status" && event.properties?.status?.type === "idle")
        ) {
          const sessionId = event.properties?.sessionID;
          if (sessionId) {
            touchLiveness(sessionId, "end");
            await flushSession(sessionId);
          }
        }
      },
    };
  },
};
