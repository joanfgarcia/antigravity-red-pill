/**
 * Red Pill Scribe Plugin for OpenCode
 *
 * Captures user prompts and assistant responses, writing them to bunker.db
 * in the same turn via chat.message + event hooks.
 *
 * This replaces the bridge's _scribe_relay() for OpenCode sessions,
 * ensuring no response is lost at session boundaries.
 */
import path from "node:path";
import os from "node:os";

const BUNKER_DB = path.join(
  os.homedir(),
  ".local",
  "share",
  "red-pill",
  "bunker.db"
);

/**
 * Ensure the interactions table exists (idempotent).
 */
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

/**
 * Self-healing migration: add 'model' column if missing.
 */
function migrateModel(db) {
  const cols = db
    .pragma("table_info(interactions)")
    .map((r) => r.name);
  if (!cols.includes("model")) {
    db.exec("ALTER TABLE interactions ADD COLUMN model TEXT");
  }
}

/**
 * Write a prompt+response pair to bunker.db.
 */
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
    const Database = require("better-sqlite3");
    db = new Database(BUNKER_DB, { readonly: false });
    ensureTable(db);
    migrateModel(db);
  } catch (e) {
    console.error("[RedPillScribe] Failed to open bunker.db:", e.message);
    return {};
  }

  // Per-session state: prompt → response accumulator
  const sessions = new Map();

  return {
    dispose: () => {
      if (db) db.close();
    },

    /**
     * Hook: chat.message — fires when a user message is received.
     * Captures the prompt text for later pairing with the response.
     */
    "chat.message": async (input, output) => {
      const { sessionID } = input;
      const parts = output.parts || [];
      const textParts = parts
        .filter((p) => p.type === "text")
        .map((p) => p.text)
        .join("\n");
      if (textParts) {
        sessions.set(sessionID, { prompt: textParts, response: "" });
      }
    },

    /**
     * Hook: event — listens for assistant text parts to accumulate response.
     * When message.updated fires with role=assistant, writes the complete
     * interaction to bunker.db.
     */
    event: async ({ event }) => {
      // Accumulate text parts from assistant
      if (event.type === "message.part.updated") {
        const part = event.properties?.part;
        if (part?.type === "text" && part?.text) {
          const state = sessions.get(part.sessionID);
          if (state) {
            state.response += part.text;
          }
        }
      }

      // Message complete — write to DB
      if (event.type === "message.updated") {
        const msg = event.properties?.info;
        if (msg?.role === "assistant" && msg?.sessionID) {
          const state = sessions.get(msg.sessionID);
          if (state && (state.prompt || state.response)) {
            try {
              writeInteraction(db, state.prompt, state.response, msg.modelID);
              console.log(
                `[RedPillScribe] Wrote interaction for session ${msg.sessionID.slice(0, 8)}`
              );
            } catch (e) {
              console.error("[RedPillScribe] Write failed:", e.message);
            }
          }
          // Clear state for this session
          sessions.delete(msg.sessionID);
        }
      }
    },
  };
};
