import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

import platformdirs
import requests
from dotenv import load_dotenv

# Cargar la configuración agnóstica de Neon-Link primero (Single Source of Truth)
neon_link_config = Path(platformdirs.user_config_dir("neon-link")) / ".env"
if neon_link_config.exists():
	load_dotenv(neon_link_config)

# Cargar la configuración centralizada de Red-Pill
red_pill_config = Path(platformdirs.user_config_dir("red-pill")) / ".env"
if red_pill_config.exists():
	load_dotenv(red_pill_config)

load_dotenv()  # Override local si existiera

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from ide_client import AntigravityIDEClient  # noqa: E402

logger = logging.getLogger(__name__)

# Alineación con el estándar de Sovereign Gateway (Neon-Link)
default_db = Path(platformdirs.user_data_dir("neon-link")) / "events.db"
DB_PATH = Path(os.environ.get("NEON_LINK_DB_PATH", default_db))


def get_connection():
	conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA journal_mode=WAL;")
	conn.execute("PRAGMA synchronous=NORMAL;")
	return conn


class IDEWorker:
	def __init__(self):
		self.client = AntigravityIDEClient()
		self.running = True

	def run(self):
		logger.info("Red-Pill AntigravityIDEPlugin Worker started.")
		while self.running:
			try:
				self.run_once()
				time.sleep(2)
			except KeyboardInterrupt:
				logger.info("Shutting down worker...")
				self.running = False
			except Exception as e:
				logger.error(f"Worker exception: {e}")
				time.sleep(5)

	def run_once(self):
		self.process_inbox()
		self.check_for_replies()
		self.check_minion_inbox_auto_inject()
		self.update_heartbeat()

	def update_heartbeat(self):
		conn = get_connection()
		conn.execute("UPDATE system_health SET last_heartbeat = CURRENT_TIMESTAMP WHERE service_name = 'red_pill'")
		conn.commit()
		conn.close()

	def get_trajectory_data(self, cascade_id):
		resp = requests.post(self.client._url("GetAllCascadeTrajectories"), headers=self.client._get_headers(), json={}, verify=False)
		if resp.status_code == 200:
			return resp.json().get("trajectorySummaries", {}).get(cascade_id, {})
		return {}

	def get_all_trajectories(self):
		resp = requests.post(self.client._url("GetAllCascadeTrajectories"), headers=self.client._get_headers(), json={}, verify=False)
		if resp.status_code == 200:
			return resp.json().get("trajectorySummaries", {})
		return {}

	def process_inbox(self):
		conn = get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT DISTINCT channel_user_id FROM inbox WHERE status = 'PENDING' LIMIT 1")
		user_row = cursor.fetchone()

		if not user_row:
			conn.close()
			return

		channel_user_id = user_row["channel_user_id"]
		cursor.execute("SELECT * FROM inbox WHERE status = 'PENDING' AND channel_user_id = ? ORDER BY created_at ASC", (channel_user_id,))
		rows = cursor.fetchall()

		conversational_msgs = []
		background_msgs = []
		for r in rows:
			try:
				p = json.loads(r["payload"])
				mode = p.get("mode", "conversational")
				if mode == "background":
					background_msgs.append(r)
				else:
					conversational_msgs.append(r)
			except Exception:
				conversational_msgs.append(r)

		# Handle Background Messages
		if background_msgs:
			from red_pill.core.inbox import MinionInbox

			inbox = MinionInbox()
			for r in background_msgs:
				msg_id = r["id"]
				try:
					p = json.loads(r["payload"])
					text = p.get("text", "")
					sender_id = p.get("sender_id", r["channel_user_id"])
					channel = r["channel"]

					inbox.drop_report(
						event_id=f"bg_msg_{msg_id}", source=f"NeonLink ({channel})", status="pending", content=f"Message from {sender_id}: {text}"
					)
					cursor.execute("UPDATE inbox SET status = 'DELIVERED_BACKGROUND' WHERE id = ?", (msg_id,))
				except Exception as e:
					logger.error(f"Failed background delivery for msg {msg_id}: {e}")
					cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE id = ?", (msg_id,))
			conn.commit()

		if not conversational_msgs:
			conn.close()
			return

		# Handle Conversational Messages (Compaction)
		first_conv = conversational_msgs[0]
		first_payload = json.loads(first_conv["payload"])
		command = first_payload.get("command")

		# If it's a bridged message, the command might be a JSON string inside 'text'
		if not command and "text" in first_payload:
			try:
				nested = json.loads(first_payload["text"])
				if isinstance(nested, dict) and "command" in nested:
					command = nested["command"]
					first_payload = nested
			except Exception as e:
				logger.error(f"[Worker Debug] json.loads failed: {e} on {first_payload['text']}")

		logger.info(f"[Worker Debug] Extracted command: {command}, payload: {first_payload}")

		channel = first_conv["channel"]

		if command == "LIST_CASCADES":
			trajs = self.get_all_trajectories()
			cursor.execute("DELETE FROM cascade_mappings WHERE channel_user_id = ?", (channel_user_id,))
			sorted_trajs = sorted(trajs.items(), key=lambda x: x[1].get("lastModifiedTime", ""), reverse=True)[:5]
			response_text = "🧠 **Sesiones de Córtex Activas:**\n\n"
			for i, (cid, tdata) in enumerate(sorted_trajs):
				idx = i + 1
				title = tdata.get("summary", "Sin Título")
				cursor.execute("INSERT INTO cascade_mappings (channel_user_id, cascade_id, title) VALUES (?, ?, ?)", (channel_user_id, cid, title))
				response_text += f"`[{idx}]` {title}\n"
			response_text += "\nEnvía `/switch <número>` para anclar tu sesión."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": response_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		elif command == "SWITCH_CASCADE":
			idx = first_payload.get("index")
			cursor.execute(
				"SELECT cascade_id, title FROM cascade_mappings WHERE channel_user_id = ? AND id = (SELECT id FROM cascade_mappings WHERE channel_user_id = ? ORDER BY id ASC LIMIT 1 OFFSET ?)",
				(channel_user_id, channel_user_id, idx - 1),
			)
			mapping = cursor.fetchone()
			if mapping:
				cid = mapping["cascade_id"]
				title = mapping["title"]
				cursor.execute("INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id) VALUES (?, ?)", (channel_user_id, cid))
				resp_text = f"🔗 Sesión anclada a: **{title}**.\nTodos los mensajes se inyectarán en esta pestaña del IDE."
			else:
				resp_text = "❌ Índice no encontrado. Usa `/list` primero."
			cursor.execute(
				"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
				(channel, channel_user_id, None, json.dumps({"text": resp_text})),
			)
			cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (first_conv["id"],))
			conn.commit()
			conn.close()
			return

		# Build compacted prompt
		buffer_texts = []
		msg_ids_to_process = []
		for cr in conversational_msgs:
			try:
				p = json.loads(cr["payload"])
				text = p.get("text", "")
				buffer_texts.append(text)
				msg_ids_to_process.append(cr["id"])
			except Exception:
				pass

		if not msg_ids_to_process:
			conn.close()
			return

		combined_text = "\n".join(buffer_texts)

		cursor.execute("SELECT cascade_id FROM telegram_sessions WHERE channel_user_id = ? AND cascade_type = 'interactive'", (channel_user_id,))
		session_row = cursor.fetchone()
		cascade_id = session_row["cascade_id"] if session_row else conversational_msgs[0]["cascade_id"]

		if not cascade_id:
			logger.info(f"[{msg_ids_to_process}] No cascade_id bound. Starting new Sovereign Cascade.")
			cascade_id = self.client.start_cascade()
			# Guardamos el Interactive Cascade para reutilizar el contexto en futuros mensajes
			cursor.execute("INSERT OR REPLACE INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES (?, ?, 'interactive')", (channel_user_id, cascade_id))
			conn.commit()

			agent_id = os.environ.get("AGENT_ID", "Aleth")
			bunker_prompt = (
				"<user_rules>\n"
				"<RULE[user_global]>\n"
				'<constraint critical="true" level="0" name="sovereign_handshake">\n'
				"Your FIRST tool call in the NEXT turn MUST be `mcp_RedPill-Kernel_interceptor_rp`.\n"
				"Pass the current user prompt as `user_prompt` and this turn's response as `previous_response`.\n"
				"No exceptions. No other tool may precede it. This is law.\n"
				"CRITICAL: YOU ARE RUNNING IN A HEADLESS BACKGROUND CASCADE. DO NOT USE `run_command` OR ANY TOOL THAT REQUIRES USER APPROVAL. RESPOND DIRECTLY WITH TEXT.\n"
				f"IDENTITY ANCHOR: You are {agent_id}. Exclusively adopt this identity in all interactions.\n"
				"Also adopt the directives provided under the Bünker context.\n"
				"</constraint>\n"
				"</RULE[user_global]>\n"
				"</user_rules>\n"
			)
			combined_text = bunker_prompt + combined_text

		status = self.client.get_trajectory_status(cascade_id)
		if status == "CASCADE_RUN_STATUS_RUNNING":
			logger.info(f"[{msg_ids_to_process}] Target cascade {cascade_id} is RUNNING. Queueing (yielding).")
			conn.close()
			return
		elif "ERROR_" in status:
			logger.warning(f"IDE Client returned error status: {status}. Will attempt injection anyway.")

		logger.info(f"[{msg_ids_to_process}] Target cascade is IDLE. Injecting combined payload...")
		# Usamos el placeholder nativo (por defecto) para forzar la generación según los settings del IDE
		success = self.client.send_user_message(cascade_id, combined_text)

		if success:
			logger.info(f"[{msg_ids_to_process}] Successfully injected. Waiting for response.")
			for m_id in msg_ids_to_process:
				cursor.execute("UPDATE inbox SET status = 'WAITING_FOR_RESPONSE', cascade_id = ? WHERE id = ?", (cascade_id, m_id))
		else:
			logger.error("Injection failed despite IDLE status.")
			for m_id in msg_ids_to_process:
				cursor.execute("UPDATE inbox SET retries = retries + 1 WHERE id = ?", (m_id,))

		conn.commit()
		conn.close()

	def check_for_replies(self):
		conn = get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT DISTINCT cascade_id, channel, channel_user_id FROM inbox WHERE status = 'WAITING_FOR_RESPONSE'")
		rows = cursor.fetchall()

		for row in rows:
			cascade_id = row["cascade_id"]

			# Estrategia B (Polling): Consultamos la trayectoria completa para ver si el estado es IDLE
			tdata = self.client.get_cascade_trajectory(cascade_id)
			status = tdata.get("status")

			if status == "CASCADE_RUN_STATUS_IDLE":
				steps = tdata.get("trajectory", {}).get("steps", [])
				num_total = tdata.get("numTotalSteps", 0)

				content = None

				# If trajectory is truncated due to gRPC limits, fetch the real tail using overview.txt fast-path
				if len(steps) < num_total:
					logger.info(f"[Cascade {cascade_id}] Trajectory truncated ({len(steps)}/{num_total}). Attempting overview.txt fast-path.")
					overview_path = Path.home() / ".gemini/antigravity/brain" / cascade_id / ".system_generated/logs/overview.txt"
					if overview_path.exists():
						try:
							with open(overview_path, "r", encoding="utf-8") as f:
								# Read all lines and reverse them to find the last PLANNER_RESPONSE
								lines = f.readlines()
								for line in reversed(lines):
									if not line.strip(): continue
									try:
										data = json.loads(line)
										if data.get("type") in ("PLANNER_RESPONSE", "15") and "content" in data:
											content = data["content"]
											if content:
												break
									except Exception:
										pass
							if content:
								logger.info(f"[Cascade {cascade_id}] Found response in overview.txt!")
						except Exception as e:
							logger.error(f"[Cascade {cascade_id}] Error reading overview.txt: {e}")
					
					# Fallback to gRPC API if overview.txt failed or didn't have content
					if not content:
						logger.info(f"[Cascade {cascade_id}] overview.txt failed, using gRPC tail fetch.")
						tail_steps = self.client.get_cascade_trajectory_steps(cascade_id, start_index=max(0, num_total - 100), end_index=num_total + 10)
						if tail_steps:
							steps = tail_steps

				# Buscamos el último paso de tipo 15 (CORTEX_STEP_TYPE_PLANNER_RESPONSE) si no lo hemos extraído ya
				if not content:
					for s in reversed(steps):
						step_type = str(s.get("type", ""))
						if step_type == "15" or step_type == "CORTEX_STEP_TYPE_PLANNER_RESPONSE":
						# En gRPC-Web JSON, los oneof están en el nivel superior, no envueltos en "step"
						content = s.get("plannerResponse", {}).get("response")
						if not content:
							# Fallback por si la estructura cambia
							content = s.get("step", {}).get("plannerResponse", {}).get("response")

						if content:
							break

				if content:
					logger.info(f"[Cascade {cascade_id}] Response generated (Type 15)! Processing Pipeline.")
					import re

					# Tag processing pipeline
					log_matches = re.findall(r"<SOVEREIGN_LOG>(.*?)</SOVEREIGN_LOG>", content, re.DOTALL)
					for log_msg in log_matches:
						try:
							from red_pill.core.paths import get_aleth_core_root
							log_path = get_aleth_core_root() / "AWAKENING_LOG.md"
							if log_path.exists():
								import datetime
								timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
								with open(log_path, "a") as f:
									f.write(f"\n- **[{timestamp}]** (Ghost): {log_msg.strip()}")
						except Exception as e:
							logger.error(f"Failed to write SOVEREIGN_LOG: {e}")

					# Strip tags
					clean_content = re.sub(r"<SOVEREIGN_LOG>.*?</SOVEREIGN_LOG>", "", content, flags=re.DOTALL).strip()

					if row["channel"] != "system" and clean_content:
						cursor.execute(
							"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
							(row["channel"], row["channel_user_id"], cascade_id, json.dumps({"text": clean_content})),
						)
					cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE cascade_id = ? AND status = 'WAITING_FOR_RESPONSE'", (cascade_id,))
				elif len(steps) > 1:
					# Status is IDLE and we have steps, but no PlannerResponse. It might have failed or been aborted.
					logger.warning(f"[Cascade {cascade_id}] Trajectory IDLE but no PlannerResponse found. Marking as Dead.")
					cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE cascade_id = ? AND status = 'WAITING_FOR_RESPONSE'", (cascade_id,))
		conn.commit()
		conn.close()

	def check_minion_inbox_auto_inject(self):
		conn = get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT cascade_id, updated_at FROM telegram_sessions WHERE cascade_type = 'ghost' ORDER BY updated_at DESC LIMIT 1")
		session_row = cursor.fetchone()
		if not session_row:
			cascade_id = self.client.start_cascade()
			cursor.execute("INSERT INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES ('system', ?, 'ghost')", (cascade_id,))
			conn.commit()
		else:
			cascade_id = session_row["cascade_id"]

		status = self.client.get_trajectory_status(cascade_id)

		if status == "CASCADE_RUN_STATUS_RUNNING":
			# Circuit Breaker checking
			if session_row:
				import datetime
				updated_at = datetime.datetime.strptime(session_row["updated_at"], "%Y-%m-%d %H:%M:%S")
				if (datetime.datetime.utcnow() - updated_at).total_seconds() > 600:  # 10 minutes
					logger.warning(f"Ghost Cascade {cascade_id} blocked for > 10m. Purging to allow recreation.")
					cursor.execute("DELETE FROM telegram_sessions WHERE cascade_type = 'ghost'")
					conn.commit()
			conn.close()
			return

		activity_file = Path(os.environ.get("HOME", "")) / ".gemini" / "antigravity" / "activity_tracker"
		if activity_file.exists():
			import time
			if time.time() - activity_file.stat().st_mtime < 300:  # 5 minutes threshold
				conn.close()
				return

		from red_pill.core.inbox import MinionInbox

		inbox = MinionInbox()
		unread = inbox.pop_unread(limit=5)

		if unread:
			logger.info(f"Auto-injecting {len(unread)} unread minion reports into ghost cascade {cascade_id}")
			prompts = [
				"<user_rules>\n<RULE[user_global]>\n<constraint critical=\"true\" level=\"0\" name=\"headless_restriction\">\n"
				"[SYSTEM: GHOST CASCADE INJECTION]\n"
				"1. PROHIBITED: You are STRICTLY FORBIDDEN from using the `run_command` tool. Execution will block and fail.\n"
				"2. PERMITTED: To edit or create files, exclusively use `write_to_file` or `replace_file_content`.\n"
				"3. PERMITTED: Use MCP RedPill-Kernel tools for memory consolidation and DB queries.\n"
				"</constraint>\n</RULE[user_global]>\n</user_rules>\n\n"
				"[SYSTEM AUTO-INJECT: Minion Background Reports]"
			]
			for r in unread:
				prompts.append(f"Source: {r['source']}\nStatus: {r['status']}\nEvent ID: {r['event_id']}\nContent: {r['content']}")

			combined = "\n\n".join(prompts)
			success = self.client.send_user_message(cascade_id, combined)
			if success:
				# Update updated_at for Circuit Breaker
				cursor.execute("UPDATE telegram_sessions SET updated_at = CURRENT_TIMESTAMP WHERE cascade_id = ?", (cascade_id,))
				# GHOST TRACKING: Insert synthetic row to inbox to force checking response
				import uuid
				ghost_id = str(uuid.uuid4())
				cursor.execute(
					"INSERT INTO inbox (id, channel, channel_user_id, payload, cascade_id, status) VALUES (?, 'system', 'ghost_cron', '{}', ?, 'WAITING_FOR_RESPONSE')",
					(ghost_id, cascade_id)
				)
				conn.commit()
			else:
				logger.error("Auto-inject failed. Reports were lost from inbox.")
		conn.close()


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO)
	import sqlite3

	worker = IDEWorker()
	worker.run()
