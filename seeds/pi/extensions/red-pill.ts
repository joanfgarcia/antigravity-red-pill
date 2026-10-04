// Red Pill ↔ Pi bridge extension (pi-coding-agent).
//
// The per-turn RAG goes through the RedPill-Kernel MCP server (`bunker_memory_api`
// action `recall`) over a persistent stdio connection, instead of spawning the
// red-pill CLI every turn. The client is `@earendil-works/pi-mcp` (the standalone
// MCP client published with Pi, pinned to Pi's version); the injector provisions
// it under `~/.pi/agent/node_modules`. Identity injection (runWake) and the
// on-demand tools stay on the CLI for now. The `red-pill` binary is NOT on the
// PATH of the harness: it lives in the checkout (`.venv/bin/red-pill`) and is
// invoked via `uv run --no-sync` from the red-pill directory. The
// `${RED_PILL_DIR}` / `${UV}` placeholders are resolved by
// `scripts/inject/pi/inject.py` at seeding time.
//
// Skills are NOT exposed here: the injector copies the red-pill skills into
// `~/.pi/agent/skills/`, which pi auto-discovers (single merged dir, so the
// IDE-specific override wins and there are no name collisions).
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const RED_PILL_DIR = process.env.RED_PILL_DIR ?? "${RED_PILL_DIR}";
const UV = process.env.UV_BIN ?? "${UV}";
const TIMEOUT_MS = 20000;
const LIGHT_TIMEOUT_MS = 20000;
// Umbral de relevancia para el recall liviano (sobreescribible con RED_PILL_SCORE_THRESHOLD).
const SCORE_THRESHOLD = parseFloat(process.env.RED_PILL_SCORE_THRESHOLD ?? "0.7");
// Queue DB (single sink the kernel worker drains) — same path the Claude Code
// Stop hook and the opencode scribe plugin write to.
const XDG_DATA = process.env.XDG_DATA_HOME ?? join(homedir(), ".local", "share");
const QUEUE_DB = join(XDG_DATA, "red-pill", "queue", "bunker_queue.db");
const RELAY_DEDUP_WINDOW_S = 12 * 3600;

/** Filtra el output de `red-pill search`: conserva solo bullets con (Score: N >= umbral). */
function filterByScore(output: string): string {
	const lines = output.split("\n");
	const kept: string[] = [];
	let pendingHeader: string | null = null;
	let headerKept = false;
	const flushHeader = () => {
		if (pendingHeader !== null && !headerKept) { /* se descarta si no aporta bullets */ }
		pendingHeader = null;
		headerKept = false;
	};
	for (const line of lines) {
		const m = line.match(/\(Score:\s*([0-9.]+)\)/);
		if (m) {
			if (parseFloat(m[1]) >= SCORE_THRESHOLD) {
				if (pendingHeader !== null && !headerKept) { kept.push(pendingHeader); headerKept = true; }
				kept.push(line);
			}
			continue;
		}
		if (/^---\s*\[RESULTS/.test(line)) { flushHeader(); pendingHeader = line; continue; }
		if (pendingHeader !== null) { /* línea sin score dentro de un bloque: se ignora */ continue; }
		if (line.trim()) kept.push(line);
	}
	return kept.join("\n").trim();
}

function rp(...args: string[]) {
	return execFileAsync(UV, ["run", "--no-sync", "red-pill", ...args], {
		timeout: TIMEOUT_MS,
		maxBuffer: 512 * 1024,
		cwd: RED_PILL_DIR,
	});
}

function runWake(mode = "full"): Promise<string> {
	return execFileAsync(UV, ["run", "--no-sync", "scripts/wake_up_v6.py", "--mode", mode], {
		timeout: TIMEOUT_MS,
		maxBuffer: 512 * 1024,
		cwd: RED_PILL_DIR,
	}).then(
		(r) => (r.stdout ?? "").trim(),
		() => "",
	);
}

// ── Persistent MCP client (single process) ──────────────────────────────
// One stdio connection to RedPill-Kernel shared by every hook. The import is
// lazy on purpose: a missing @earendil-works/pi-mcp degrades only the RAG
// (recall returns ""), instead of breaking the whole bridge at load time.
// A dropped connection clears the singleton so the next call reconnects lazily.
type McpClientT = import("@earendil-works/pi-mcp").McpClient;
let mcpModulePromise: Promise<typeof import("@earendil-works/pi-mcp")> | null = null;
let mcpClientPromise: Promise<McpClientT> | null = null;

function loadMcpModule() {
	mcpModulePromise ??= import("@earendil-works/pi-mcp");
	return mcpModulePromise;
}

function getMcpClient(): Promise<McpClientT> {
	if (mcpClientPromise) return mcpClientPromise;
	mcpClientPromise = (async () => {
		const { McpClient, StdioTransport } = await loadMcpModule();
		const serverPath = RED_PILL_DIR + "/src/red_pill/mcp_server.py";
		const client = new McpClient({ name: "red-pill-pi", version: "1.0.0", requestTimeoutMs: LIGHT_TIMEOUT_MS });
		client.onClose(() => {
			mcpClientPromise = null;
		});
		await client.connect(
			new StdioTransport({
				command: UV,
				args: ["--directory", RED_PILL_DIR, "run", "--no-sync", "python", serverPath],
				stderr: "pipe",
			}),
		);
		return client;
	})().catch((e) => {
		mcpClientPromise = null;
		throw e;
	});
	return mcpClientPromise;
}

function mcpResultText(result: { content?: unknown }): string {
	const content = result?.content;
	if (!Array.isArray(content)) return "";
	return content.map((c: any) => (c?.type === "text" && typeof c.text === "string" ? c.text : "")).join("");
}

async function recall(query: string, collection: string, limit: number): Promise<string> {
	const clean = query.slice(0, 1500).replace(/\s+/g, " ").trim();
	if (!clean) return "";
	try {
		const client = await getMcpClient();
		const result = await client.callTool("bunker_memory_api", {
			action: "recall",
			payload: { query: clean, collection, limit },
		});
		return filterByScore(mcpResultText(result).trim());
	} catch {
		return ""; // Búnker caído/offline → degradación silenciosa
	}
}

/** Silent Scribe Relay: queue the completed turn straight into `memory_queue`
 * (like the Claude Code Stop hook and the opencode scribe plugin), instead of
 * spawning Python. Raw insert — the queue worker filters tooling noise at the
 * single drain point. Fire-and-forget: never blocks or throws into the turn. */
function relay(prevPrompt: string, prevResponse: string, model: string, sessionId: string) {
	if (prevPrompt.trim().length < 20 && prevResponse.trim().length < 20) return;
	void (async () => {
		try {
			const { DatabaseSync } = await import("node:sqlite");
			if (!existsSync(QUEUE_DB)) return; // kernel never ran here (no table to create)
			const db = new DatabaseSync(QUEUE_DB);
			try {
				db.exec("PRAGMA journal_mode=WAL");
				const cols = new Set(
					(db.prepare("PRAGMA table_info(memory_queue)").all() as Array<{ name: string }>).map((r) => r.name),
				);
				if (cols.size === 0) return;
				const contentHash = createHash("sha256").update(`${prevPrompt}\x00${prevResponse}`, "utf8").digest("hex");
				if (cols.has("content_hash")) {
					const dup = db
						.prepare("SELECT id FROM memory_queue WHERE content_hash = ? AND created_at > ? LIMIT 1")
						.get(contentHash, Date.now() / 1000 - RELAY_DEDUP_WINDOW_S);
					if (dup) return;
				}
				const fields = ["prompt", "response", "role", "status", "created_at", "category", "originator", "model"];
				const values: Array<string | number | null> = [
					prevPrompt.slice(0, 4000),
					prevResponse.slice(0, 8000),
					"assistant",
					"pending",
					Date.now() / 1000,
					"mixed",
					"pi",
					model || null,
				];
				if (cols.has("content_hash")) {
					fields.push("content_hash");
					values.push(contentHash);
				}
				if (cols.has("session_id") && cols.has("affinity")) {
					fields.push("session_id", "affinity");
					values.push(sessionId || null, null);
				}
				const placeholders = fields.map(() => "?").join(", ");
				db.prepare(`INSERT INTO memory_queue (${fields.join(", ")}) VALUES (${placeholders})`).run(...values);
			} finally {
				db.close();
			}
		} catch {
			/* best-effort: a relay failure must never break the turn */
		}
	})();
}

function assistantTextOf(messages: any[]): string {
	// Solo el texto del assistant: concatenar user/system/custom_message (el
	// blob de identidad+RAG inyectado) contamina el engrama con el contexto
	// en vez de la respuesta real.
	let out = "";
	for (const m of messages ?? []) {
		if (m?.role !== "assistant") continue;
		const c = m?.content;
		if (typeof c === "string") out += c + "\n";
		else if (Array.isArray(c))
			for (const b of c) if (b?.type === "text" && b.text) out += b.text + "\n";
	}
	return out.trim();
}

export default function (pi: ExtensionAPI) {
	if (process.env.RED_PILL_ENABLED === "0") return;

	// ── FULL handshake: identidad completa solo en pérdida de contexto ──
	// session_start (startup/new/resume/fork), cambio de modelo, post-compactación.
	let pendingIdentity: string | null = null;
	let needFull = false;

	pi.on("session_start", async () => {
		pendingIdentity = (await runWake("full")) || null;
		needFull = !!pendingIdentity;
	});

	pi.on("model_select", async () => {
		pendingIdentity = (await runWake("full")) || null;
		needFull = !!pendingIdentity;
	});

	pi.on("session_compact", async () => {
		pendingIdentity = (await runWake("full")) || null;
		needFull = !!pendingIdentity;
	});

	// Close the persistent MCP connection when the session ends.
	pi.on("session_shutdown", async () => {
		if (mcpClientPromise) {
			try {
				(await mcpClientPromise).close();
			} catch {
				/* noop */
			}
			mcpClientPromise = null;
		}
	});

	// ── Turno: prompt + respuesta del assistant. El relay va por HOOKS (nunca por
	//    el LLM): no hay que acordarse de llamar a nada. ──
	let prevPrompt = "";
	let lastModel = "";
	let turnResponse = ""; // último texto NO vacío del assistant (sin thinking/tool calls)
	let boundarySeen = false;

	const sessionIdOf = (ctx: any): string => {
		try {
			return ctx?.sessionManager?.getSessionId() ?? "";
		} catch {
			return ""; // sesión efímera (--no-session)
		}
	};

	pi.on("before_agent_start", async (event, ctx) => {
		const prompt = event.prompt ?? "";
		if (prompt.trim().length < 3) return;
		prevPrompt = prompt;
		turnResponse = "";
		boundarySeen = false;
		lastModel = ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : "";

		const chunks: string[] = [];

		// FULL solo si hubo pérdida de contexto (inicio / modelo / compactación)
		if (needFull && pendingIdentity) {
			chunks.push(`[BÚNKER IDENTIDAD — resync completo]\n${pendingIdentity}`);
			needFull = false;
			pendingIdentity = null;
		}

		// LIGHT siempre: RAG liviano (equivale al pipeline del interceptor)
		const [work, directives] = await Promise.all([
			recall(prompt, "work", 2),
			recall(prompt, "directive", 2),
		]);
		if (directives) chunks.push(`[BÚNKER DIRECTIVAS]\n${directives}`);
		if (work) chunks.push(`[BÚNKER CONTEXTO]\n${work}`);
		if (!chunks.length) return;

		return {
			message: {
				customType: "red-pill",
				content: chunks.join("\n---\n"),
				display: false,
			},
		};
	});

	// Respuesta = SOLO bloques de texto del assistant (message_end, no streaming;
	// gana el último no vacío). Thinking y tool calls quedan fuera.
	pi.on("message_end", async (event) => {
		if ((event.message as any)?.role !== "assistant") return;
		const text = assistantTextOf([event.message as any]);
		if (text) turnResponse = text;
	});

	// Boundary final CON outcome: guarda solo turnos COMPLETADOS (salta abort/error).
	// `agent_before_settle` es el último punto con la proyección reparada (tras
	// reintentos/compactación) y dispara una vez por settle.
	pi.on("agent_before_settle", async (event, ctx) => {
		boundarySeen = true;
		if (event.outcome !== "completed") return;
		relay(prevPrompt, turnResponse, lastModel, sessionIdOf(ctx));
	});

	// Fallback para Pi <0.87 (sin `agent_before_settle`): `agent_settled` es el
	// hook final y garantiza UNA ejecución cuando Pi ya no va a seguir solo.
	pi.on("agent_settled", async (_event, ctx) => {
		if (boundarySeen) return;
		relay(prevPrompt, turnResponse, lastModel, sessionIdOf(ctx));
	});

	// Búsqueda manual bajo demanda
	pi.registerTool({
		name: "bunker_search",
		label: "Bunker Search",
		description: "Busca en la memoria vectorial del Búnker (red-pill). Colecciones: work, social, directive, story, interaction.",
		parameters: Type.Object({
			query: Type.String({ description: "Texto a buscar" }),
			collection: Type.Optional(Type.String({ description: "Colección (por defecto work)" })),
			limit: Type.Optional(Type.Number({ description: "Nº de resultados (por defecto 3)" })),
		}),
		async execute(_toolCallId, params) {
			const text = await recall(params.query, params.collection ?? "work", params.limit ?? 3);
			return { content: [{ type: "text" as const, text: text || "(sin resultados en el Búnker)" }], details: {} };
		},
	});

	// Guardado explícito (el relay + el archivo nocturno vía chronicle_sources/pi
	// lo cubren todo; esto es solo para fijar algo importante a mano)
	pi.registerTool({
		name: "bunker_save",
		label: "Bunker Save",
		description: "Guarda un engrama en la memoria del Búnker (red-pill add).",
		parameters: Type.Object({
			text: Type.String({ description: "Contenido a recordar" }),
			collection: Type.Optional(Type.String({ description: "Colección (por defecto work)" })),
		}),
		async execute(_toolCallId, params) {
			try {
				await rp("add", params.collection ?? "work", params.text);
				return { content: [{ type: "text" as const, text: "[OK] Engrama guardado en el Búnker." }], details: {} };
			} catch (e) {
				return { content: [{ type: "text" as const, text: `[ERROR] No se pudo guardar: ${String(e).slice(0, 200)}` }], details: {} };
			}
		},
	});

	pi.registerCommand("bunker", {
		description: "Estado del Búnker red-pill (status del interceptor)",
		handler: async (_args, ctx) => {
			try {
				const { stdout } = await rp("interceptor", "status");
				ctx.ui.notify((stdout ?? "").trim() || "Búnker sin respuesta", "info");
			} catch {
				ctx.ui.notify("Búnker offline (red-pill CLI no responde)", "error");
			}
		},
	});
}