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

import { mkdirSync, writeFileSync } from "node:fs";

const QUEUE_DB = "${QUEUE_DB}";
const STATE_DIR = "${STATE_DIR}";
const ORIGINATOR = "opencode";
const DISABLED = process.env.REDPILL_SCRIBE_DISABLE === "1";

// ── SESSION LIVENESS (RFC-DESPERTAR-001, P4) ────────────────────────────────
// Touch de un fichero vacío por turno: `.start` al recibir el prompt, `.end` al
// terminar el turno. mtime = señal; el par detecta "en vuelo". Best-effort:
// nunca rompe el turno. Ver red_pill/core/session_liveness.py.
function touchLiveness(sessionId, phase) {
  if (!sessionId || !STATE_DIR || STATE_DIR.includes("${")) return;
  try {
    const safe = String(sessionId).replace(/\//g, "_").replace(/__/g, "_");
    const dir = `${STATE_DIR}/sessions/live`;
    mkdirSync(dir, { recursive: true });
    writeFileSync(`${dir}/${ORIGINATOR}__${safe}.${phase}`, "");
  } catch (_) {}
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

function writeInteraction(db, prompt, response, model, sessionId, cols) {
  if (!prompt && !response) return;
  // Full text on purpose: truncating here would silently mutilate the engram
  // downstream. Noise trimming is the worker's job, at the single drain point.
  // session_id se captura cuando el esquema lo lleva (single-writer); la afinidad
  // del cwd se retiró (AD-034).
  if (cols.has("session_id") && cols.has("affinity")) {
    const stmt = db.prepare(
      "INSERT INTO memory_queue (prompt, response, role, status, created_at, category, originator, model, session_id, affinity) " +
        "VALUES (?, ?, 'assistant', 'pending', ?, 'mixed', ?, ?, ?, ?)"
    );
    stmt.run(prompt || "", response || "", Date.now() / 1000, ORIGINATOR, model || null, sessionId || null, null);
  } else {
    const stmt = db.prepare(
      "INSERT INTO memory_queue (prompt, response, role, status, created_at, category, originator, model) " +
        "VALUES (?, ?, 'assistant', 'pending', ?, 'mixed', ?, ?)"
    );
    stmt.run(prompt || "", response || "", Date.now() / 1000, ORIGINATOR, model || null);
  }
}

let storePromise = null;

async function initStore() {
  try {
    const { Database } = await import("bun:sqlite");
    const db = new Database(QUEUE_DB);
    db.exec("PRAGMA journal_mode=WAL");
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
  const state = sessions.get(sessionId);
  if (!state) return;

  if (type === "session.step.started") {
    const model = data.model;
    if (model?.id) state.modelID = model.providerID ? `${model.providerID}/${model.id}` : model.id;
    return;
  }

  if (type === "session.text.delta") {
    if (typeof data.delta === "string" && data.delta) state.response += data.delta;
    return;
  }

  if (type === "session.execution.succeeded" || type === "session.execution.failed") {
    touchLiveness(sessionId, "end");
    await flushSession(sessionId);
  }
}

export default {
  id: "redpill-scribe",

  async setup(ctx) {
    // Si el proceso fue lanzado por un bridge red-pill (Telegram/awakenings/
    // minions), el bridge ya relaya el turno a la cola: el plugin se abstiene
    // para no duplicar (y para no capturar el prompt envuelto sin respuesta).
    if (DISABLED) return;
    if (typeof ctx?.session?.hook !== "function" || typeof ctx?.event?.subscribe !== "function") return;

    await ctx.session.hook("prompt", (event) => {
      const sessionId = event?.sessionID;
      const text = event?.prompt?.text;
      if (sessionId) touchLiveness(sessionId, "start");
      if (sessionId && text) {
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

  async server() {
    if (DISABLED) return {};

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
        if (sessionID) touchLiveness(sessionID, "start");
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
          if (part?.type === "text" && part?.text && part?.sessionID) {
            const state = sessions.get(part.sessionID);
            if (!state) return;

            if (!state.userMsgIDs.has(part.messageID)) {
              state.response += part.text;
            }
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
