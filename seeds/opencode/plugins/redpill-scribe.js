/**
 * Red Pill Scribe Plugin for OpenCode
 *
 * ── ROLE IN THE ARCHITECTURE ─────────────────────────────────────────────
 * This plugin is the RAW CAPTURE LAYER for opencode sessions. It writes
 * prompt+response pairs to bunker.db's `interactions` table via SQLite WAL.
 *
 * DATA PIPELINE (3 stages):
 *   1. THIS PLUGIN → bunker.db interactions (raw text, this file)
 *   2. Queue Worker → bunker_queue.db → Qdrant (embeddings, Python)
 *   3. Sleep Cycle → social_memories / work_memories (consolidation, Python)
 *
 * Stages 2 and 3 are pure Python (red-pill kernel). This plugin only handles
 * stage 1. Do NOT add embedding, Qdrant, or consolidation logic here.
 *
 * ── CONCURRENCY ──────────────────────────────────────────────────────────
 * This plugin and the Python MCP server share bunker.db via SQLite WAL mode.
 * WAL allows concurrent readers + single writer without blocking. Both sides
 * must enable WAL on connection:
 *   JS:  db.exec("PRAGMA journal_mode=WAL")
 *   Python: conn.execute("PRAGMA journal_mode=WAL")
 *
 * The schema is idempotent (CREATE TABLE IF NOT EXISTS, ALTER IF MISSING).
 * If you change the schema here, you MUST also update:
 *   - src/red_pill/swarm/bridges/opencode.py  (_scribe_relay migration)
 *   - src/red_pill/plugins/antigravity_ide/worker.py  (same pattern)
 *   - Any Python code that reads `interactions` from bunker.db
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
 * BUNKER_DB path is injected at deploy time by inject_opencode.py.
 * Runtime: Bun — uses bun:sqlite.
 */

const BUNKER_DB = "${BUNKER_DB}";

function ensureTable(db) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS interactions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_prompt TEXT,
      agent_response TEXT,
      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
      model TEXT
    )
  `);
}

function migrateModel(db) {
  const cols = db.query("PRAGMA table_info(interactions)").all().map((r) => r.name);
  if (!cols.includes("model")) {
    db.exec("ALTER TABLE interactions ADD COLUMN model TEXT");
  }
}

function writeInteraction(db, prompt, response, model) {
  if (!prompt && !response) return;
  const stmt = db.prepare(
    "INSERT INTO interactions (user_prompt, agent_response, timestamp, model) VALUES (?, ?, CURRENT_TIMESTAMP, ?)"
  );
  stmt.run(
    (prompt || "").slice(0, 2000),
    (response || "").slice(0, 5000),
    model || null
  );
}

/** @type {import("@opencode-ai/plugin").Plugin} */
export const RedPillScribe = async (ctx) => {
  let db;
  try {
    const { Database } = await import("bun:sqlite");
    db = new Database(BUNKER_DB);
    db.exec("PRAGMA journal_mode=WAL");
    ensureTable(db);
    migrateModel(db);
  } catch (e) {
    console.error("[RedPillScribe] Failed to open bunker.db:", e.message);
    return {};
  }

  const sessions = new Map();

  return {
    dispose: async () => {
      for (const [sid, state] of sessions) {
        if (state?.prompt) {
          try { writeInteraction(db, state.prompt, state.response, state.modelID); } catch (_) {}
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
            writeInteraction(db, state.prompt, state.response, state.modelID);
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
