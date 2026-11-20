/**
 * Red Pill Context — inyección de identidad por hook en Pi (RFC-HARNESS-001 · P4).
 *
 * Sustituye la inyección que hacía `red-pill.ts` en `before_agent_start` (que
 * devolvía un mensaje **persistido**: pagaba identidad en cada turno posterior y
 * encima se perdía con la compactación).
 *
 * Aquí se usa `pi.on("context")`, que corre **antes de cada petición al modelo y no
 * se persiste**: la identidad sobrevive a la compactación y no engorda el
 * transcript. Las herramientas no se declaran aquí: el perfil (`local-9b`) deja el
 * kernel en `codemode`/0 declaradas, y el Búnker se alcanza por script.
 *
 * Contrato (RFC_HARNESS_001/CONTRATO_HOOK.md):
 *   - `full`  → identidad; en frío el kernel responde `retry_full` y calcula en
 *               segundo plano (wake_up_v6 tarda 2,3-2,7 s: no se espera).
 *   - `light` → 1 línea de telemetría.
 *   - ack     → al terminar el turno, con la respuesta (`agent_before_settle`).
 *
 * Fail-open por contrato: si el kernel no está, el turno sigue sin identidad.
 */

import http from "node:http";
import os from "node:os";
import path from "node:path";

const TIMEOUT_MS = 1500;

function socketPath(): string {
	if (process.env.REDPILL_MCP_SOCKET) return process.env.REDPILL_MCP_SOCKET;
	const data = process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share");
	return path.join(data, "red-pill", "state", "mcp.sock");
}

function hookCall(route: string, body: unknown): Promise<any | null> {
	return new Promise((resolve) => {
		let done = false;
		const finish = (value: any) => {
			if (!done) {
				done = true;
				resolve(value);
			}
		};
		try {
			const req = http.request(
				{
					socketPath: socketPath(),
					path: route,
					method: "POST",
					headers: { "content-type": "application/json" },
					timeout: TIMEOUT_MS,
				},
				(res) => {
					let buf = "";
					res.setEncoding("utf8");
					res.on("data", (c) => (buf += c));
					res.on("end", () => {
						if ((res.statusCode || 500) >= 400) return finish(null);
						try {
							finish(JSON.parse(buf));
						} catch {
							finish(null);
						}
					});
				},
			);
			req.on("error", () => finish(null));
			req.on("timeout", () => {
				req.destroy();
				finish(null);
			});
			req.write(JSON.stringify(body ?? {}));
			req.end();
		} catch {
			finish(null);
		}
	});
}

function renderBlock(block: any): string {
	if (!block || typeof block.text !== "string" || !block.text) return "";
	if (block.trusted === false) {
		return `<redpill_data origin="${block.origin || "?"}" trusted="false">\n${block.text}\n</redpill_data>`;
	}
	return block.text;
}

type TurnState = {
	turn: number;
	prompt: string;
	response: string;
	blocks: any[];
	delivery: string | null;
	identitySeen: boolean;
	pendingFull: boolean;
	model: string;
};

export default function (pi: any) {
	if ((process.env.REDPILL_HARNESS_MODE || "auto").toLowerCase() === "off") return;

	const sessions = new Map<string, TurnState>();
	const state = (sid: string): TurnState => {
		let st = sessions.get(sid);
		if (!st) {
			st = {
				turn: 0,
				prompt: "",
				response: "",
				blocks: [],
				delivery: null,
				identitySeen: false,
				pendingFull: true,
				model: "",
			};
			sessions.set(sid, st);
		}
		return st;
	};
	const sidOf = (ctx: any): string => {
		try {
			return ctx?.sessionManager?.getSessionId() ?? "";
		} catch {
			return "";
		}
	};

	// ── turno: pedir contexto al arrancar el agente ─────────────────────────
	pi.on("before_agent_start", async (event: any, ctx: any) => {
		const sid = sidOf(ctx);
		if (!sid) return;
		const st = state(sid);
		st.turn += 1;
		st.prompt = event?.prompt ?? "";
		st.response = "";
		st.blocks = [];
		st.model = ctx?.model ? `${ctx.model.provider}/${ctx.model.id}` : st.model;
		const need = st.pendingFull || !st.identitySeen ? "full" : "light";
		const res = await hookCall("/hook/context", {
			session_id: sid,
			harness: "pi",
			model: st.model,
			turn: st.turn,
			prompt: st.prompt,
			need,
			reason: st.turn === 1 ? "session_start" : "kernel_trigger",
			workdir: process.cwd(),
		});
		if (!res) return; // kernel caído: se sigue sin identidad (O2)
		st.delivery = res.delivery_id ?? null;
		st.blocks = Array.isArray(res.blocks) ? res.blocks : [];
		if (st.blocks.some((b) => b.kind === "identity")) {
			st.identitySeen = true;
			st.pendingFull = false;
		}
		if (res.hint === "retry_full") st.pendingFull = true;
	});

	// ── contexto por petición (NO persistido) ───────────────────────────────
	pi.on("context", async (event: any, ctx: any) => {
		const sid = sidOf(ctx);
		const st = sessions.get(sid);
		if (!st) return;
		const texts = st.blocks.map(renderBlock).filter(Boolean);
		if (!texts.length) return;
		// Contrato REAL del hook: devolver `{ messages }`, no `{ message }`.
		// Con la forma anterior pi lo ignoraba EN SILENCIO: la identidad del hook nunca
		// llegaba al modelo (lo único que identificaba era el AGENTS.override).
		return {
			messages: [
				...event.messages,
				{ role: "system", content: texts.join("\n\n"), timestamp: Date.now() },
			],
		};
	});

	// ── respuesta y cierre de turno ─────────────────────────────────────────
	pi.on("message_end", async (event: any, ctx: any) => {
		const sid = sidOf(ctx);
		const st = sessions.get(sid);
		if (!st) return;
		const msg = event?.message ?? {};
		if (msg?.role !== "assistant") return;
		const content = Array.isArray(msg.content) ? msg.content : [];
		const text = content
			.filter((part: any) => part?.type === "text" && typeof part.text === "string")
			.map((part: any) => part.text)
			.join("");
		if (text) st.response = text;
	});

	pi.on("agent_before_settle", async (event: any, ctx: any) => {
		const sid = sidOf(ctx);
		const st = sessions.get(sid);
		if (!st || !st.delivery) return;
		const delivered = event?.outcome === "completed";
		await hookCall("/hook/ack", {
			session_id: sid,
			harness: "pi",
			turn: st.turn,
			delivery_id: st.delivery,
			seq: 0,
			delivered,
			response: st.response,
			source: delivered ? "hook:agent_before_settle" : "hook:agent_before_settle:failed",
		});
		st.delivery = null; // un ack por turno
	});
}
