import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))
import requests
from ide_client import AntigravityIDEClient

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / "Documents" / "IA" / "sharing" / "storage" / "events.db"


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
				self.process_inbox()
				self.check_for_replies()
				self.update_heartbeat()
				time.sleep(2)
			except KeyboardInterrupt:
				logger.info("Shutting down worker...")
				self.running = False
			except Exception as e:
				logger.error(f"Worker exception: {e}")
				time.sleep(5)

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

		cursor.execute("SELECT * FROM inbox WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT 1")
		row = cursor.fetchone()

		if not row:
			conn.close()
			return

		msg_id = row["id"]
		payload_str = row["payload"]
		retries = row["retries"]
		channel = row["channel"]
		channel_user_id = row["channel_user_id"]

		try:
			payload = json.loads(payload_str)
			command = payload.get("command")
			text = payload.get("text", "")

			# Handle Control Commands
			if command == "LIST_CASCADES":
				trajs = self.get_all_trajectories()
				cursor.execute("DELETE FROM cascade_mappings WHERE channel_user_id = ?", (channel_user_id,))

				# Sort by lastModifiedTime (most recent first)
				sorted_trajs = sorted(trajs.items(), key=lambda x: x[1].get("lastModifiedTime", ""), reverse=True)[:5]

				response_text = "🧠 **Sesiones de Córtex Activas:**\n\n"
				for i, (cid, tdata) in enumerate(sorted_trajs):
					idx = i + 1
					title = tdata.get("summary", "Sin Título")
					cursor.execute(
						"INSERT INTO cascade_mappings (channel_user_id, cascade_id, title) VALUES (?, ?, ?)", (channel_user_id, cid, title)
					)
					response_text += f"`[{idx}]` {title}\n"

				response_text += "\nEnvía `/switch <número>` para anclar tu sesión."
				cursor.execute(
					"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
					(channel, channel_user_id, None, json.dumps({"text": response_text})),
				)
				cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (msg_id,))
				conn.commit()
				conn.close()
				return

			elif command == "SWITCH_CASCADE":
				idx = payload.get("index")
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
				cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (msg_id,))
				conn.commit()
				conn.close()
				return

			# Normal Message Injection
			# Check for bound session
			cursor.execute("SELECT cascade_id FROM telegram_sessions WHERE channel_user_id = ?", (channel_user_id,))
			session_row = cursor.fetchone()
			cascade_id = session_row["cascade_id"] if session_row else row["cascade_id"]

			if not cascade_id:
				logger.info(f"[{msg_id}] No cascade_id bound. Starting new Ghost Cascade.")
				cascade_id = self.client.start_cascade()

			status = self.client.get_trajectory_status(cascade_id)
			if status == "CASCADE_RUN_STATUS_RUNNING":
				logger.info(f"[{msg_id}] Target cascade {cascade_id} is RUNNING. Queueing (yielding).")
				conn.close()
				return
			elif "ERROR_" in status:
				raise RuntimeError(f"IDE Client returned error status: {status}")

			logger.info(f"[{msg_id}] Target cascade is IDLE. Injecting payload...")
			success = self.client.send_user_message(cascade_id, text)

			if success:
				logger.info(f"[{msg_id}] Successfully injected. Waiting for response.")
				cursor.execute("UPDATE inbox SET status = 'WAITING_FOR_RESPONSE', cascade_id = ? WHERE id = ?", (cascade_id, msg_id))
			else:
				raise RuntimeError("Injection failed despite IDLE status.")

		except Exception as e:
			logger.error(f"[{msg_id}] Processing failed: {e}")
			retries += 1
			if retries >= 3:
				logger.warning(f"[{msg_id}] Max retries reached. Moving to DLQ.")
				cursor.execute(
					"INSERT INTO dead_letters (original_table, original_id, channel, channel_user_id, payload, error_reason) VALUES (?, ?, ?, ?, ?, ?)",
					("inbox", msg_id, row["channel"], row["channel_user_id"], payload_str, str(e)),
				)
				cursor.execute("UPDATE inbox SET status = 'DEAD' WHERE id = ?", (msg_id,))
			else:
				cursor.execute("UPDATE inbox SET retries = ? WHERE id = ?", (retries, msg_id))

		conn.commit()
		conn.close()

	def check_for_replies(self):
		conn = get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT * FROM inbox WHERE status = 'WAITING_FOR_RESPONSE'")
		rows = cursor.fetchall()

		for row in rows:
			msg_id = row["id"]
			cascade_id = row["cascade_id"]

			status = self.client.get_trajectory_status(cascade_id)
			if status == "CASCADE_RUN_STATUS_IDLE":
				tdata = self.get_trajectory_data(cascade_id)
				content = tdata.get("latestNotifyUserStep", {}).get("step", {}).get("notifyUser", {}).get("notificationContent")
				if content:
					logger.info(f"[{msg_id}] Response generated! Sending to Outbox.")
					cursor.execute(
						"INSERT INTO outbox (channel, channel_user_id, cascade_id, payload) VALUES (?, ?, ?, ?)",
						(row["channel"], row["channel_user_id"], cascade_id, json.dumps({"text": content})),
					)
					cursor.execute("UPDATE inbox SET status = 'PROCESSED' WHERE id = ?", (msg_id,))
				else:
					# Trajectory became IDLE but no text yet? Maybe it's still finalizing.
					pass
		conn.commit()
		conn.close()


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO)
	import sqlite3

	worker = IDEWorker()
	worker.run()
