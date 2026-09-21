/**
 * Red Pill Scribe Plugin for OpenCode
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
 * ── HOOK LIFECYCLE ───────────────────────────────────────────────────────
 *   chat.message         → capture user prompt
 *   message.updated      → on user: track msg ID; on assistant: FLUSH to DB
 *   message.part.updated → accumulate assistant response text (streaming)
 *   dispose              → flush remaining buffers on plugin unload
 *
 * NOTE: session.idle / session.status events do NOT fire reliably in
 * opencode 1.18.x. We use message.updated(role=assistant) as the flush
 * trigger instead.
 *
 * ── WHY NOT CALL PYTHON DIRECTLY? ───────────────────────────────────────
 * Bun.spawn per turn adds ~50-100ms overhead. The plugin is intentionally
 * minimal (~80 lines of logic): capture hooks + single INSERT. All heavy
 * processing (embeddings, Qdrant, sleep) lives in tested Python code.
 * DRY is maintained by keeping this plugin as a thin capture shim only.
 *
 * QUEUE_DB path is injected at deploy time by inject_opencode.py.
 * Runtime: Bun — uses bun:sqlite.
 */

const QUEUE_DB = "${QUEUE_DB}";
const ORIGINATOR = "opencode";

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

function deriveAffinity(_dir) {
  // AD-034/D15: la afinidad por filesystem (cwd/proyecto) se RETIRÓ — no refleja
  // cómo trabajamos. La afinidad (si se retoma) será semántica (keywords del refine)
  // o explícita. Aquí se deja vacía.
  return [];
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

/** @type {import("@opencode-ai/plugin").Plugin} */
export const RedPillScribe = async (ctx) => {
  // Si el proceso fue lanzado por un bridge red-pill (Telegram/awakenings/
  // minions), el bridge ya relaya el turno a la cola: el plugin se abstiene
  // para no duplicar (y para no capturar el prompt envuelto sin respuesta).
  if (process.env.REDPILL_SCRIBE_DISABLE === "1") return {};
  let db;
  let COLS = new Set();
  try {
    const { Database } = await import("bun:sqlite");
    db = new Database(QUEUE_DB);
    db.exec("PRAGMA journal_mode=WAL");
    if (!hasQueue(db)) {
      console.error("[RedPillScribe] memory_queue missing; run the red-pill kernel once. Capture disabled.");
      db.close();
      return {};
    }
    COLS = queueColumns(db);
  } catch (e) {
    console.error("[RedPillScribe] Failed to open the queue:", e.message);
    return {};
  }

  const sessions = new Map();

  return {
    dispose: async () => {
      for (const [sid, state] of sessions) {
        if (state?.prompt) {
          try { writeInteraction(db, state.prompt, state.response, state.modelID, sid, COLS); } catch (_) {}
        }
      }
      sessions.clear();
      if (db) db.close();
    },

    "chat.message": async (input, output) => {
      const { sessionID } = input;
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

        if (msg.role === "assistant") {
          state.modelID = msg.modelID;
          try {
            writeInteraction(db, state.prompt, state.response, state.modelID, msg.sessionID, COLS);
          } catch (e) {
            console.error("[RedPillScribe] Write failed:", e.message);
          }
          sessions.delete(msg.sessionID);
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
      }
    },
  };
};
