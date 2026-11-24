// Red Pill ↔ Pi bridge extension (pi-coding-agent).
//
// The per-turn RAG goes through the RedPill-Kernel MCP server (`bunker_memory_api`
// action `recall`) over a persistent stdio connection, instead of spawning the
// red-pill CLI every turn. The client is a minimal JSON-RPC loop over the kernel's
// `mcp_proxy` (no external npm package: offline boxes had no
// `@earendil-works/pi-mcp` and the RAG died in silence). Identity injection lives
// in `red-pill-context.ts`; the on-demand tools stay on the CLI for now. The
// `red-pill` binary is NOT on the PATH of the harness: it lives in the checkout
// (`.venv/bin/red-pill`) and is invoked via `uv run --no-sync` from the red-pill
// directory. The `${RED_PILL_DIR}` / `${UV}` / `${PYTHON}` / `${MCP_SOCKET}`
// placeholders are resolved by `scripts/inject/pi/inject.py` at seeding time.
//
// Skills are NOT exposed here: the injector copies the red-pill skills into
// `~/.pi/agent/skills/`, which pi auto-discovers (single merged dir, so the
// IDE-specific override wins and there are no name collisions).
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const RED_PILL_DIR = process.env.RED_PILL_DIR ?? "${RED_PILL_DIR}";
const UV = process.env.UV_BIN ?? "${UV}";
const TIMEOUT_MS = 20000;
const LIGHT_TIMEOUT_MS = 20000;
// Umbral de relevancia para el recall liviano (sobreescribible con RED_PILL_SCORE_THRESHOLD).
// 0.55 y no 0.7: medido el 2026-11-24, el embedding de 384d puntúa 0.47-0.58 las
// paráfrasis legítimas y 0.7 solo deja pasar casi-literales (m2: 0/3 inyectado a
// 0.7, 3/3 a 0.55, mismo acierto y 1.1 tool calls menos). Las memorias sin
// relación puntúan por debajo de 0.5 y siguen fuera.
const SCORE_THRESHOLD = parseFloat(process.env.RED_PILL_SCORE_THRESHOLD ?? "0.55");
// Queue DB (single sink the kernel worker drains) — same path the Claude Code
// Stop hook and the opencode scribe plugin write to.
const XDG_DATA = process.env.XDG_DATA_HOME ?? join(homedir(), ".local", "share");
const QUEUE_DB = join(XDG_DATA, "red-pill", "queue", "bunker_queue.db");
const RELAY_DEDUP_WINDOW_S = 12 * 3600;
// Session liveness (RFC-DESPERTAR-001, P4): same `${STATE_DIR}/sessions/live`
// pair the opencode plugin and the Claude Code hooks write. Without it a Pi
// session is invisible to the autonomous-cron idle heuristic and to the board.
const LIVE_DIR = join(XDG_DATA, "red-pill", "state", "sessions", "live");

/** Touch `<provider>__<session>.<phase>`; mtime is the signal. Best-effort. */
function touchLiveness(sessionId: string, phase: "start" | "end") {
	if (!sessionId) return;
	try {
		const safe = String(sessionId).replace(/\//g, "_").replace(/__/g, "_");
		mkdirSync(LIVE_DIR, { recursive: true });
		writeFileSync(join(LIVE_DIR, `pi__${safe}.${phase}`), "");
	} catch {
		/* best-effort: a failed heartbeat never breaks the turn */
	}
}

// ── WRITE-AHEAD (B-01h) ──────────────────────────────────────────────────
// Mismo journal JSON que Claude/opencode; el kernel lo importa al espejo.
const TURN_JOURNAL_DISABLED = process.env.REDPILL_TURN_JOURNAL_DISABLE === "1";
const TURN_ROOT = join(XDG_DATA, "red-pill", "state", "external_turns");

function safeTurn(token: string): string {
	return String(token ?? "").replace(/[/:]/g, "_").replace(/__/g, "_");
}

function turnCurrent(sessionId: string): string {
	return join(TURN_ROOT, "current", `pi__${safeTurn(sessionId)}.json`);
}

function turnArchive(sessionId: string, requestId: string): string {
	return join(TURN_ROOT, "archive", `pi__${safeTurn(sessionId)}__${safeTurn(requestId)}.json`);
}

function writeTurnJson(path: string, data: any): void {
	const tmp = `${path}.tmp`;
	mkdirSync(path.slice(0, path.lastIndexOf("/")), { recursive: true });
	writeFileSync(tmp, JSON.stringify(data));
	renameSync(tmp, path);
}

function readTurnJson(path: string): any | null {
	try {
		return JSON.parse(readFileSync(path, "utf8"));
	} catch {
		return null;
	}
}

function beginExternalTurn(sessionId: string, prompt: string, cwd: string): void {
	if (TURN_JOURNAL_DISABLED || !sessionId || !prompt.trim()) return;
	try {
		const current = turnCurrent(sessionId);
		const previous = readTurnJson(current);
		if (previous?.status === "pending") {
			if (previous.prompt === prompt) return;
			previous.status = "aborted";
			previous.reason = "superseded";
			previous.ended_at = Date.now() / 1000;
			writeTurnJson(turnArchive(sessionId, previous.request_id || "unknown"), previous);
		}
		writeTurnJson(current, {
			provider: "pi",
			session_id: sessionId,
			originator: `pi:${sessionId}`,
			request_id: `pi:${sessionId}:${Date.now()}:${Math.random().toString(16).slice(2, 10)}`,
			prompt,
			cwd,
			model: null,
			started_at: Date.now() / 1000,
			status: "pending",
		});
	} catch {
		/* best-effort */
	}
}

function finishExternalTurn(sessionId: string, response: string, status: "completed" | "aborted", reason = "", model = ""): void {
	if (TURN_JOURNAL_DISABLED || !sessionId) return;
	try {
		const current = turnCurrent(sessionId);
		const data = readTurnJson(current);
		if (!data) return;
		data.status = status;
		data.response = response || "";
		data.reason = reason || null;
		data.model = model || data.model || null;
		data.ended_at = Date.now() / 1000;
		writeTurnJson(turnArchive(sessionId, data.request_id || "unknown"), data);
		unlinkSync(current);
	} catch {
		/* best-effort */
	}
}

/** Filtra el output del recall: conserva solo bullets con score >= umbral.
 *
 *  Formatos que debe entender:
 *  - MCP `bunker_memory_api recall` (el que usa el RAG por turno):
 *    `- [COLOR][Int: 1.0] contenido (sim 0.74 · util 0.00)` y, para inmunes,
 *    `- […] contenido [IMMUNE · sim 0.74]`.
 *  - CLI `red-pill search` (legado): `- … (Score: 0.74)`.
 *
 *  El parser anterior solo aceptaba `(Score: N)` y descartaba TODOS los hits del
 *  MCP: el recall devolvía texto, `filterByScore` lo vaciaba y el RAG por turno
 *  no inyectaba nada (en silencio). Medido 2026-11-24. */
function filterByScore(output: string): string {
	const lines = output.split("\n");
	const kept: string[] = [];
	let header: string | null = null;
	let headerKept = false;
	for (const line of lines) {
		if (/^---\s*\[RESULTS/.test(line)) { header = line; continue; }
		if (!line.startsWith("- ")) continue; // punteros, no_recall y prosa: fuera
		const m = line.match(/\(Score:\s*([0-9.]+)\)/) ?? line.match(/sim\s+([0-9.]+)/);
		if (!m || parseFloat(m[1]) < SCORE_THRESHOLD) continue;
		if (header !== null && !headerKept) { kept.push(header); headerKept = true; }
		kept.push(line);
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


// ── Persistent MCP client (single process, stdio JSON-RPC) ──────────────
// One connection to RedPill-Kernel shared by every hook. We speak the minimum
// of MCP the bridge needs (`initialize` + `tools/call`) over the kernel's
// `mcp_proxy`, so the extension has no npm dependency. A missing socket falls
// back to the direct `mcp_server.py`; a dead child clears the singleton and the
// next turn reconnects. Any failure degrades to "" (never breaks the turn).
const MCP_SOCKET = "${MCP_SOCKET}";
const PYTHON_BIN =
	process.env.RED_PILL_PYTHON ?? (existsSync("${PYTHON}") ? "${PYTHON}" : "/opt/py/bin/python");

type Pending = { resolve: (value: any) => void; reject: (error: any) => void; timer: ReturnType<typeof setTimeout> };
let mcpProc: any = null;
let mcpInit: Promise<void> | null = null;
let mcpNextId = 1;
let mcpBuf = "";
const mcpPending = new Map<number, Pending>();

function mcpDrop() {
	mcpProc = null;
	mcpInit = null;
	for (const [, p] of mcpPending) {
		clearTimeout(p.timer);
		p.reject(new Error("mcp proxy closed"));
	}
	mcpPending.clear();
}

function mcpSpawn() {
	if (mcpProc) return;
	const args = existsSync(MCP_SOCKET)
		? ["-m", "red_pill.mcp_proxy", "--socket", MCP_SOCKET]
		: [join(RED_PILL_DIR, "src", "red_pill", "mcp_server.py")];
	const proc = spawn(PYTHON_BIN, args, {
		cwd: RED_PILL_DIR,
		env: { ...process.env, PYTHONPATH: join(RED_PILL_DIR, "src") },
		stdio: ["pipe", "pipe", "pipe"],
	});
	mcpProc = proc;
	mcpBuf = "";
	proc.stdout.on("data", (chunk: any) => {
		mcpBuf += chunk.toString();
		let nl = mcpBuf.indexOf("\n");
		while (nl >= 0) {
			const line = mcpBuf.slice(0, nl).trim();
			mcpBuf = mcpBuf.slice(nl + 1);
			nl = mcpBuf.indexOf("\n");
			if (!line) continue;
			let msg: any;
			try {
				msg = JSON.parse(line);
			} catch {
				continue;
			}
			if (msg?.id == null) continue; // notificación (logging, progress…)
			const p = mcpPending.get(Number(msg.id));
			if (!p) continue;
			mcpPending.delete(Number(msg.id));
			clearTimeout(p.timer);
			if (msg.error) p.reject(new Error(String(msg.error?.message ?? "mcp error")));
			else p.resolve(msg.result);
		}
	});
	proc.stderr.on("data", () => {
		/* el proxy loguea a stderr: no es un error del turno */
	});
	proc.on("exit", mcpDrop);
	proc.on("error", mcpDrop);
}

function mcpRequest(method: string, params: any): Promise<any> {
	mcpSpawn();
	const proc = mcpProc;
	return new Promise((resolve, reject) => {
		if (!proc?.stdin?.writable) {
			reject(new Error("mcp proxy no disponible"));
			return;
		}
		const id = mcpNextId++;
		const timer = setTimeout(() => {
			mcpPending.delete(id);
			reject(new Error(`mcp ${method} timeout`));
		}, LIGHT_TIMEOUT_MS);
		mcpPending.set(id, { resolve, reject, timer });
		try {
			proc.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
		} catch (error) {
			clearTimeout(timer);
			mcpPending.delete(id);
			reject(error);
		}
	});
}

function mcpReady(): Promise<void> {
	mcpInit ??= (async () => {
		await mcpRequest("initialize", {
			protocolVersion: "2024-11-05",
			capabilities: {},
			clientInfo: { name: "red-pill-pi", version: "1.0.0" },
		});
		mcpProc?.stdin?.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
	})().catch((error) => {
		mcpInit = null;
		throw error;
	});
	return mcpInit;
}

function mcpClose() {
	const proc = mcpProc;
	mcpDrop();
	if (!proc) return;
	try {
		proc.stdin?.end();
	} catch {
		/* noop */
	}
	try {
		proc.kill();
	} catch {
		/* noop */
	}
}

/** `tools/call` con el contrato MCP: `{ content: [{type:"text", text}], isError? }`. */
async function mcpCallTool(name: string, args: any): Promise<any> {
	await mcpReady();
	return mcpRequest("tools/call", { name, arguments: args });
}

function mcpResultText(result: { content?: unknown }): string {
	const content = result?.content;
	if (!Array.isArray(content)) return "";
	return content.map((c: any) => (c?.type === "text" && typeof c.text === "string" ? c.text : "")).join("");
}

// El handler de `recall` valida contra el enum de colecciones completas: los
// alias (`work`, `directive`…) que documenta la tool no pasan por el proxy.
const COLLECTION_ALIASES: Record<string, string> = {
	work: "work_memories",
	social: "social_memories",
	directive: "directive_memories",
	story: "story_memories",
	interaction: "interaction_memories",
};

async function recall(query: string, collection: string, limit: number): Promise<string> {
	const clean = query.slice(0, 1500).replace(/\s+/g, " ").trim();
	if (!clean) return "";
	try {
		const result = await mcpCallTool("bunker_memory_api", {
			action: "recall",
			payload: { query: clean, collection: COLLECTION_ALIASES[collection] ?? collection, limit },
		});
		if (result?.isError) return ""; // server-side validation failure → degrade, don't inject the error
		return filterByScore(mcpResultText(result).trim());
	} catch {
		return ""; // Búnker caído/offline → degradación silenciosa
	}
}

/** Sovereign Handshake (F5) por el cliente MCP compartido: emite/recupera el alma
 * (`continuity_id`) y ata `pi:<session_id> ↔ alma` en session_registry (el resolver
 * Python es el único escritor autoritativo). Solo se invoca en pérdida de contexto
 * (start/modelo/compact), no por turno. NO carga identidad (`is_new_session:false`):
 * la identidad la sirve `red-pill-context.ts` por el hook. Best-effort: nunca tira el turno. */
async function handshake(sessionId: string, userPrompt: string): Promise<void> {
	try {
		await mcpCallTool("sovereign_handshake", {
			user_prompt: (userPrompt || "(session wake)").slice(0, 1500),
			mode: "low",
			is_new_session: false,
			originator: sessionId ? `pi:${sessionId}` : "pi",
		});
	} catch {
		/* best-effort: un fallo del handshake nunca debe romper el turno */
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
					sessionId ? `pi:${sessionId}` : "pi",
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

	// ── Identidad: YA NO se inyecta aquí ────────────────────────────────
	// RFC-HARNESS-001 (P4): la identidad la inyecta `red-pill-context.ts` vía
	// `context` (no persistido). Aquí sólo queda la captura y el relay del turno.


	// `session_start` / `model_select` / `session_compact`: la identidad la pide
	// `red-pill-context.ts` al kernel por el hook (P4). Aquí no se arranca ningún
	// `wake_up_v6`: eran 2,3-2,7 s por evento para un texto que ya nadie inyectaba.
	//
	// Lo que NO se retira es el handshake MCP: su trabajo no es inyectar texto,
	// es atar `pi:<session_id> ↔ alma` en session_registry (paridad Alma, F5).
	// Sin él, en el modo arnés sin extensión de contexto la sesión no tendría
	// alma propia. Una vez por sesión y best-effort: coste despreciable.
	pi.on("session_start", async (_event, ctx) => {
		void handshake(sessionIdOf(ctx), "");
	});

	// Close the persistent MCP connection when the session ends.
	pi.on("session_shutdown", async (_event, ctx) => {
		touchLiveness(sessionIdOf(ctx), "end");
		mcpClose();
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
		const sessionId = sessionIdOf(ctx);
		touchLiveness(sessionId, "start");
		beginExternalTurn(sessionId, prompt, process.cwd());
		prevPrompt = prompt;
		turnResponse = "";
		boundarySeen = false;
		lastModel = ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : "";

		const chunks: string[] = [];

		// Identidad: la sirve `red-pill-context.ts` por el hook (no persistido).
		// El antiguo `runWake` + mensaje persistido pagaba identidad en cada turno
		// posterior y se perdía con la compactación: eso es lo que P4 retira.

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
		const msg = (event.message as any) ?? {};
		if (msg?.role === "assistant") {
			const text = assistantTextOf([msg]);
			if (text) turnResponse = text;
		}
	});

	// Boundary final CON outcome: guarda solo turnos COMPLETADOS (salta abort/error).
	// `agent_before_settle` es el último punto con la proyección reparada (tras
	// reintentos/compactación) y dispara una vez por settle.
	pi.on("agent_before_settle", async (event, ctx) => {
		boundarySeen = true;
		const sessionId = sessionIdOf(ctx);
		touchLiveness(sessionId, "end");
		if (event.outcome !== "completed") {
			finishExternalTurn(sessionId, turnResponse, "aborted", String(event.outcome || "aborted"), lastModel);
			return;
		}
		finishExternalTurn(sessionId, turnResponse, "completed", "", lastModel);
		relay(prevPrompt, turnResponse, lastModel, sessionId);
	});

	// Fallback para Pi <0.87 (sin `agent_before_settle`): `agent_settled` es el
	// hook final y garantiza UNA ejecución cuando Pi ya no va a seguir solo.
	pi.on("agent_settled", async (_event, ctx) => {
		const sessionId = sessionIdOf(ctx);
		touchLiveness(sessionId, "end");
		if (boundarySeen) return;
		finishExternalTurn(sessionId, turnResponse, "completed", "", lastModel);
		relay(prevPrompt, turnResponse, lastModel, sessionId);
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