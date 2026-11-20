/**
 * Red Pill Harness — inyección de identidad y contexto por hook (opencode v2).
 *
 * RFC-HARNESS-001 · P2. Este plugin NO captura turnos (eso es `redpill-scribe`):
 * sólo habla con el kernel por el socket del backend (`/hook/context`, `/hook/ack`)
 * e inyecta lo que devuelve como contexto de sistema, sin persistirlo. Así la
 * identidad sobrevive a la compactación y deja de ocupar el transcript.
 *
 * Contrato (ver RFC_HARNESS_001/CONTRATO_HOOK.md):
 *   - `full`  → identidad. En frío el kernel responde `hint: retry_full` y calcula
 *               en segundo plano: NO se espera (wake_up_v6 tarda 2,3-2,7 s).
 *   - `light` → 1 línea de telemetría (OPEN LOOPS · dolor · coro · jobs · mood).
 *   - `poll`  → nada; sólo recibo.
 *   - ack     → al terminar el turno, con la respuesta: mueve el cursor del coro y
 *               sella el turno. Idempotente por `delivery_id`.
 *
 * Modos (`REDPILL_HARNESS_MODE`):
 *   - `auto` (default): inyecta y **arma el gate sólo si el hook falló** y la
 *     sesión no ha recibido identidad nunca (una caída del kernel, no un hipo).
 *   - `gate`: inyecta + gate siempre (comportamiento anterior, para A/B).
 *   - `off` : ni inyección ni gate (línea base de medición).
 *
 * Fail-open por contrato: si el kernel no está, el turno sigue. Nunca identidad
 * rancia.
 */

import http from "node:http";
import os from "node:os";
import path from "node:path";

const NAME = "redpill-harness";
const MODE = (process.env.REDPILL_HARNESS_MODE || "auto").toLowerCase();
const TIMEOUT_MS = 1500;
const MAX_REFUSALS = 3;

function socketPath() {
	if (process.env.REDPILL_MCP_SOCKET) return process.env.REDPILL_MCP_SOCKET;
	const data =
		process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share");
	return path.join(data, "red-pill", "state", "mcp.sock");
}

/** POST JSON sobre el UDS. Nunca lanza: `null` = kernel no disponible. */
function hookCall(route, body) {
	return new Promise((resolve) => {
		let done = false;
		const finish = (value) => {
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
					res.on("data", (chunk) => (buf += chunk));
					res.on("end", () => {
						if (res.statusCode >= 400) return finish(null);
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
			req.write(JSON.stringify(body));
			req.end();
		} catch {
			finish(null);
		}
	});
}

/** Bloque del kernel → texto inyectable. Lo no confiable va como DATOS. */
function renderBlock(block) {
	if (!block || typeof block.text !== "string" || !block.text) return "";
	if (block.trusted === false) {
		return `<redpill_data origin="${block.origin || "?"}" trusted="false">\n${block.text}\n</redpill_data>`;
	}
	return block.text;
}

export default {
	id: NAME,

	async setup(ctx) {
		if (typeof ctx?.session?.hook !== "function") return; // arnés sin hooks: no-op
		if (MODE === "off") return;

		const sessions = new Map();
		const state = (sid) =>
			sessions.get(sid) ||
			(() => {
				const fresh = {
					turn: 0,
					prompt: "",
					response: "",
					blocks: [],
					pendingFull: true,
					identitySeen: false,
					gateArmed: MODE === "gate",
					refusals: 0,
					delivery: null,
					seq: 0,
					model: "",
				};
				sessions.set(sid, fresh);
				return fresh;
			})();

		const sidOf = (event) =>
			event?.sessionID || event?.data?.sessionID || "global";

		// ── turno: se pide contexto al abrir ─────────────────────────────────
		await ctx.session.hook("prompt", async (event) => {
			const sid = sidOf(event);
			if (sid === "global") return;
			const st = state(sid);
			st.turn += 1;
			st.response = "";
			st.refusals = 0;
			st.prompt = event?.prompt?.text ?? event?.data?.prompt?.text ?? "";
			st.blocks = [];
			const need = st.pendingFull || !st.identitySeen ? "full" : "light";
			const res = await hookCall("/hook/context", {
				session_id: sid,
				harness: "opencode",
				model: st.model,
				turn: st.turn,
				prompt: st.prompt,
				need,
				reason: st.turn === 1 ? "session_start" : "kernel_trigger",
			});
			if (res === null) {
				// Kernel caído: se arma el gate sólo si nunca hubo identidad (D3).
				if (!st.identitySeen) {
					st.gateArmed = true;
				}
				return;
			}
			st.delivery = res.delivery_id || null;
			st.blocks = Array.isArray(res.blocks) ? res.blocks : [];
			if (st.blocks.some((b) => b.kind === "identity")) {
				st.identitySeen = true;
				st.pendingFull = false;
			}
			if (res.hint === "retry_full") st.pendingFull = true;
			if (st.identitySeen) st.gateArmed = MODE === "gate";
		});

		// ── contexto por petición (no persistido) ────────────────────────────
		await ctx.session.hook("context", (event) => {
			const sid = sidOf(event);
			if (!Array.isArray(event?.system)) return;
			const st = sessions.get(sid);
			if (!st) return;
			const texts = st.blocks.map(renderBlock).filter(Boolean);
			if (texts.length) {
				event.system.push({ type: "text", text: texts.join("\n\n") });
			}
		});

		// ── gate auto-armado ─────────────────────────────────────────────────
		if (typeof ctx?.tool?.hook === "function") {
			await ctx.tool.hook("execute.before", (event) => {
				const sid = sidOf(event);
				const st = sessions.get(sid);
				if (!st || MODE === "off") return;
				if (st.identitySeen && MODE !== "gate") return;
				if (!st.gateArmed) return;
				if (/sovereign_handshake/i.test(String(event?.tool || ""))) return;
				if (st.refusals >= MAX_REFUSALS) return; // fail-open: nunca deadlock
				st.refusals += 1;
				throw new Error(
					"HANDSHAKE REQUIRED: el hook no pudo inyectar identidad. " +
						"Llama a `sovereign_handshake` (sólo `user_prompt`) y repite. " +
						`Rechazo ${st.refusals}/${MAX_REFUSALS}.`,
				);
			});
		}

		// ── eventos: respuesta y cierre de turno ─────────────────────────────
		const controller = new AbortController();
		void (async () => {
			try {
				for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
					const sid = sidOf(event);
					const st = sessions.get(sid);
					if (!st) continue;
					const data = event?.data || event?.properties || {};
					if (event.type === "session.text.delta") {
						const delta = data?.delta;
						if (typeof delta === "string") st.response += delta;
						continue;
					}
					if (event.type === "session.step.started") {
						const model = data?.model;
						if (model?.id) st.model = model.providerID ? `${model.providerID}/${model.id}` : model.id;
						continue;
					}
					const terminal =
						event.type === "session.execution.succeeded" ||
						event.type === "session.execution.failed" ||
						event.type === "session.execution.interrupted" ||
						event.type === "session.idle" ||
						(event.type === "session.status" && data?.status?.type === "idle");
					if (terminal && st.delivery) {
						const delivered = event.type === "session.execution.succeeded" || event.type === "session.idle";
						void hookCall("/hook/ack", {
							session_id: sid,
							harness: "opencode",
							turn: st.turn,
							delivery_id: st.delivery,
							seq: st.seq,
							delivered,
							response: st.response,
							source: `event:${event.type}`,
						});
						st.delivery = null; // un ack por turno
					}
				}
			} catch {
				/* stream cerrado (reload/cierre): sin ruido */
			}
		})();

		return async () => {
			controller.abort();
		};
	},
};
