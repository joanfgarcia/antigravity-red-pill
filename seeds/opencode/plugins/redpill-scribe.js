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
 *   ctx.session.hook("prompt")   → capture user prompt
 *   session.step.started         → capture model (providerID/id)
 *   session.text.delta           → accumulate assistant response text
 *   session.execution.succeeded  → FLUSH to DB (also on .failed)
 *   cleanup (returned)           → abort event stream + flush + close
 *
 * v1 calls server(); v2 calls setup(). Both share the queue writer and the
 * per-session buffer. setup() is defensive on purpose: v1 ALSO calls it with
 * a v1 context (no session.hook / event.subscribe), where it must no-op so
 * the v1 server() hooks stay the single capture path. The entrypoint is a
 * plain object (no @opencode/plugin import): the same file loads on both
 * runtimes without npm dependencies.
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

import { mkdirSync, writeFileSync, renameSync } from "node:fs";
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

function trackSessionInfo(event) {
  const info = event?.properties?.info;
  if (!info?.id) return;
  if (event.type === "session.deleted") childSessions.delete(info.id);
  else if (info.parentID) childSessions.add(info.id);
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

// Directorio del workspace que opencode pasa al plugin (PluginInput.directory en
// v1 / ctx.directory en v2). El server MCP corre con cwd=kernel, así que este es
// el único modo de que A2 derive `repo:<rama>` del workspace REAL del agente.
let harnessCwd = "";

function writeBridge(sessionId, cwdHint) {
  if (!sessionId || childSessions.has(sessionId) || !STATE_DIR || STATE_DIR.includes("${")) return;
  try {
    const payload = {
      provider: "opencode",
      session_id: String(sessionId),
      workdir: String(cwdHint || harnessCwd || "").trim(),
      updated_at: Date.now() / 1000,
    };
    const tmp = `${BRIDGE_PATH}.${process.pid}.tmp`;
    writeFileSync(tmp, JSON.stringify(payload));
    renameSync(tmp, BRIDGE_PATH);
  } catch (_) {}
}

function pluckCwd() {
  for (const arg of arguments) {
    const v = arg?.cwd || arg?.workspaceDirectory || arg?.workspace;
    if (typeof v === "string" && v) return v;
  }
  return "";
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

async function initStore() {
  try {
    const { Database } = await import("bun:sqlite");
    const db = new Database(QUEUE_DB);
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

async function flushSession(sessionId) {
  const state = sessions.get(sessionId);
  if (!state) return;
  sessions.delete(sessionId);
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
  const sessionId = data?.sessionID;
  if (!type || !sessionId) return;

  // Fin de turno: el latido va antes del estado de captura (sin captura no hay
  // state, pero la sesión sí ha terminado su turno). flushSession sin state = no-op.
  if (type === "session.execution.succeeded" || type === "session.execution.failed") {
    touchLiveness(sessionId, "end");
    await flushSession(sessionId);
    return;
  }

  const state = sessions.get(sessionId);
  if (!state) return;

  if (type === "session.step.started") {
    const model = data.model;
    if (model?.id) state.modelID = model.providerID ? `${model.providerID}/${model.id}` : model.id;
    return;
  }

  if (type === "session.text.delta") {
    if (typeof data.delta === "string" && data.delta) state.response += data.delta;
  }
}

export default {
  id: "redpill-scribe",

  async setup(ctx) {
    // Workspace del agente (A2): ctx.directory puede no existir en versiones
    // antiguas; best-effort.
    if (typeof ctx?.directory === "string" && ctx.directory) harnessCwd = ctx.directory;
    // Si el proceso fue lanzado por un bridge red-pill (Telegram/awakenings/
    // minions), el bridge ya relaya el turno a la cola: el plugin no captura
    // (no duplica ni guarda el prompt envuelto sin respuesta), pero sí late.
    if (typeof ctx?.session?.hook !== "function" || typeof ctx?.event?.subscribe !== "function") return;

    await ctx.session.hook("prompt", (event) => {
      const sessionId = event?.sessionID;
      const text = event?.prompt?.text;
      if (sessionId) {
        touchLiveness(sessionId, "start");
        writeBridge(sessionId, pluckCwd(event, event?.data));
      }
      if (sessionId && text && !CAPTURE_DISABLED) {
        sessions.set(sessionId, { prompt: text, response: "", modelID: null, userMsgIDs: new Set() });
      }
    });

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

    return () => {
      controller.abort();
      for (const sessionId of Array.from(sessions.keys())) void flushSession(sessionId);
      closeStore();
    };
  },

  async server(input) {
    // Workspace del agente (A2): PluginInput.directory/worktree (v1). El server
    // MCP corre con cwd=checkout del kernel, así que esto alimenta el bridge.
    if (typeof input?.directory === "string" && input.directory) harnessCwd = input.directory;
    else if (typeof input?.worktree === "string" && input.worktree) harnessCwd = input.worktree;
    else if (typeof input?.app?.path?.cwd === "string" && input.app.path.cwd) harnessCwd = input.app.path.cwd;
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
          writeBridge(sessionID, pluckCwd(input, output));
        }
        if (CAPTURE_DISABLED) return;
        const parts = output.parts || [];
        const textParts = parts
          .filter((p) => p.type === "text")
          .map((p) => p.text)
          .join("\n");
        if (textParts) {
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
