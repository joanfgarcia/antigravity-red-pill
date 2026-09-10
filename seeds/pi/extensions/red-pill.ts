// Red Pill ↔ Pi bridge extension (pi-coding-agent).
//
// Pi does NOT support MCP, so the Búnker is reached through its CLI. The
// `red-pill` binary is NOT on the PATH of the harness: it lives in the
// checkout (`.venv/bin/red-pill`) and is invoked via `uv run --no-sync`
// from the red-pill directory. The `${RED_PILL_DIR}` / `${UV}` placeholders
// are resolved by `scripts/inject/pi/inject.py` at seeding time.
//
// Skills are NOT exposed here: the injector copies the red-pill skills into
// `~/.pi/agent/skills/`, which pi auto-discovers (single merged dir, so the
// IDE-specific override wins and there are no name collisions).
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const RED_PILL_DIR = process.env.RED_PILL_DIR ?? "${RED_PILL_DIR}";
const UV = process.env.UV_BIN ?? "${UV}";
const TIMEOUT_MS = 20000;
const LIGHT_TIMEOUT_MS = 20000;
// Umbral de relevancia para el recall liviano (sobreescribible con RED_PILL_SCORE_THRESHOLD).
const SCORE_THRESHOLD = parseFloat(process.env.RED_PILL_SCORE_THRESHOLD ?? "0.7");

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

async function recall(query: string, collection: string, limit: number): Promise<string> {
	const clean = query.slice(0, 1500).replace(/\s+/g, " ").trim();
	if (!clean) return "";
	try {
		const { stdout } = await execFileAsync(
			UV,
			["run", "--no-sync", "red-pill", "search", collection, "--limit", String(limit), clean],
			{ timeout: LIGHT_TIMEOUT_MS, maxBuffer: 256 * 1024, cwd: RED_PILL_DIR },
		);
		return filterByScore((stdout ?? "").trim());
	} catch {
		return ""; // Búnker caído/offline → degradación silenciosa
	}
}

/** Silent Scribe Relay: encola el turno anterior (fire-and-forget, nunca bloquea). */
function relay(prevPrompt: string, prevResponse: string, model: string) {
	if (prevPrompt.trim().length < 20 && prevResponse.trim().length < 20) return;
	const code = `
import json, sys
from red_pill.core.queue_manager import MemoryQueueManager
from red_pill.utils.telemetry_filter import filter_noise_from_turn
p, r, m = sys.argv[1], sys.argv[2], sys.argv[3] or None
cp, cr = filter_noise_from_turn(p), filter_noise_from_turn(r)
if len(cp) > 20 or len(cr) > 20:
    MemoryQueueManager().enqueue_memory(cp, cr, "assistant", category="mixed", model=m)
`;
	execFileAsync(UV, ["run", "--no-sync", "python", "-c", code, prevPrompt.slice(0, 4000), prevResponse.slice(0, 8000), model], {
		timeout: LIGHT_TIMEOUT_MS,
		cwd: RED_PILL_DIR,
	}).catch(() => {});
}

function assistantTextOf(messages: any[]): string {
	let out = "";
	for (const m of messages ?? []) {
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

	// ── Turno: guardamos prompt previo; el relay se dispara al cerrar el turno ──
	let prevPrompt = "";
	let lastModel = "";

	pi.on("before_agent_start", async (event, ctx) => {
		const prompt = event.prompt ?? "";
		if (prompt.trim().length < 3) return;
		prevPrompt = prompt;
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

	pi.on("agent_end", async (event) => {
		relay(prevPrompt, assistantTextOf(event.messages as any[]), lastModel);
		prevPrompt = "";
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