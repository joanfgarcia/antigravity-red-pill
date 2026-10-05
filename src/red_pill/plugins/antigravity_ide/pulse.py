"""AntigravityPulseStrategy — the backend-specific half of the IDEWorker pulse.

Extracted from `IDEWorker` (ARCH-001 paso B). Everything that talks to the
Antigravity IDE — the legacy gRPC polling, the `agy` autonomous operations and
the trajectory helpers — lives here, so `red_pill.core.agent_worker` stays a
neutral orchestrator.

The strategy is constructed with the worker's bridges + client and is invoked
once per pulse via ``pulse(worker)``. It mirrors the original branching:

- **legacy gRPC** backend → ``check_for_replies``, ``check_minion_inbox_auto_inject``
and ``process_cognitive_queue`` (never when ``TELEGRAM_BRIDGE_CASCADE`` is set).
This path owns the tick: it declines the core housekeeping
(``allows_core_housekeeping`` → False), as the original worker did.
- **non-gRPC** backend → ``agy`` autonomous operations, gated by
``AUTONOMOUS_AGY_ENABLED``. The Telegram session janitor and the Samantha
signal are generic: the core runs them after this tick.

The factory declines (returns None) when neither path applies, so a worker
served by other backends never builds the Antigravity client.

Trajectory helpers (``get_trajectory_data`` / ``get_all_trajectories``) are
passed through here too because they read the Antigravity gRPC client.
"""

import datetime
import json
import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

import red_pill.config as cfg
from red_pill.plugins.antigravity_ide.ide_client import AntigravityIDEClient
from red_pill.swarm.bridges import BackendType, BridgeCapabilities

if TYPE_CHECKING:
	from red_pill.core.agent_worker import IDEWorker
	from red_pill.core.pulse_strategy import PulseContext

logger = logging.getLogger(__name__)


class AntigravityPulseStrategy:
	"""Pulse steps that speak to the Antigravity IDE (legacy gRPC + agy).

	Owns its own `AntigravityIDEClient`: the neutral core never constructs or
	imports Antigravity code — it only hands over the minion bridge and receives
	this strategy. This keeps `red_pill.core` backend-agnostic.
	"""

	def __init__(self, bridge_minion, client=None) -> None:
		self._client = client if client is not None else AntigravityIDEClient()
		self._bridge_minion = bridge_minion

	@classmethod
	def applies(cls, capabilities: Optional[BridgeCapabilities]) -> bool:
		"""True if this backend has work in the worker: legacy IDE polling, or the
		autonomous agy operations (opt-in via AUTONOMOUS_AGY_ENABLED)."""
		return cls._legacy_polling(capabilities) or cfg.get_config().AUTONOMOUS_AGY_ENABLED

	def pulse(self, worker: "IDEWorker") -> None:
		"""One backend-specific tick. Never raises (worker also guards it)."""
		if self._legacy_polling(worker._caps):
			self.check_for_replies(worker)
			self.check_minion_inbox_auto_inject(worker)
			self.process_cognitive_queue(worker)
		elif cfg.get_config().AUTONOMOUS_AGY_ENABLED:
			# Autonomous agy operations (minion auto-inject, cognitive queue)
			# are gated behind AUTONOMOUS_AGY_ENABLED to prevent Flash quota
			# drain. Telegram inbox processing is NOT affected.
			self.check_minion_inbox_auto_inject_agy(worker)
			self.process_cognitive_queue_agy(worker)

	def allows_core_housekeeping(self, worker: "IDEWorker") -> bool:
		"""The legacy IDE polling path owned the whole tick (no Telegram session
		janitor, no Samantha signal); every other path leaves them to the core."""
		return not self._legacy_polling(worker._caps)

	@staticmethod
	def _is_legacy_grpc(caps: Optional[BridgeCapabilities]) -> bool:
		return caps is not None and caps.backend == BackendType.GRPC

	@classmethod
	def _legacy_polling(cls, caps: Optional[BridgeCapabilities]) -> bool:
		"""Legacy IDE polling runs only on a gRPC bridge with no cascade configured.
		gRPC capabilities WITH a configured TELEGRAM_BRIDGE_CASCADE mean the
		cascade is degraded (no target could be built): the core reports that,
		and the IDE polling path must never be resurrected on its behalf."""
		return cls._is_legacy_grpc(caps) and not cfg.get_config().TELEGRAM_BRIDGE_CASCADE

	# ── Trajectory helpers (Antigravity gRPC client) ─────────────────────────

	def get_trajectory_data(self, cascade_id):
		resp = requests.post(self._client._url("GetAllCascadeTrajectories"), headers=self._client._get_headers(), json={}, verify=False)
		if resp.status_code == 200:
			return resp.json().get("trajectorySummaries", {}).get(cascade_id, {})
		return {}

	def get_all_trajectories(self):
		resp = requests.post(self._client._url("GetAllCascadeTrajectories"), headers=self._client._get_headers(), json={}, verify=False)
		if resp.status_code == 200:
			return resp.json().get("trajectorySummaries", {})
		return {}

	# ── Legacy gRPC path ─────────────────────────────────────────────────────

	def check_for_replies(self, worker: "IDEWorker"):
		conn = worker._get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT DISTINCT cascade_id, channel, channel_user_id FROM inbox WHERE status = 'WAITING_FOR_RESPONSE'")
		rows = cursor.fetchall()

		for row in rows:
			cascade_id = row["cascade_id"]

			# Estrategia B (Polling): Consultamos la trayectoria completa para ver si el estado es IDLE
			tdata = self._client.get_cascade_trajectory(cascade_id)
			status = tdata.get("status")

			if status == "CASCADE_RUN_STATUS_IDLE":
				steps = tdata.get("trajectory", {}).get("steps", [])
				num_total = tdata.get("numTotalSteps", 0)

				content = None

				from red_pill.plugins.antigravity_ide.telegram_extractor import TelegramResponseExtractor

				extractor = TelegramResponseExtractor()
				content = extractor.get_latest_response(cascade_id)

				if not content:
					# If trajectory is truncated due to gRPC limits, fetch the real tail using gRPC API
					if len(steps) < num_total:
						logger.info(f"[Cascade {cascade_id}] Trajectory truncated ({len(steps)}/{num_total}). Using gRPC tail fetch.")
						tail_steps = self._client.get_cascade_trajectory_steps(
							cascade_id, start_index=max(0, num_total - 100), end_index=num_total + 10
						)
						if tail_steps:
							steps = tail_steps

					# Buscamos el último paso de tipo 15 (CORTEX_STEP_TYPE_PLANNER_RESPONSE)
					for s in reversed(steps):
						step_type = str(s.get("type", ""))
						if step_type in ("1", "CORTEX_STEP_TYPE_USER_INPUT", "USER_INPUT"):
							logger.info(f"[Cascade {cascade_id}] Fallback path: Hit USER_INPUT step before PLANNER_RESPONSE. Response not ready.")
							break
						if step_type == "15" or step_type == "CORTEX_STEP_TYPE_PLANNER_RESPONSE":
							content = s.get("plannerResponse", {}).get("response")
							if not content:
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
							from red_pill.core.paths import get_latest_awakening_log

							log_path = get_latest_awakening_log()
							if log_path.exists():
								timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
								with open(log_path, "a") as f:
									f.write(f"\n- **[{timestamp}]** (Ghost): {log_msg.strip()}")
						except Exception as e:
							logger.error(f"Failed to write SOVEREIGN_LOG: {e}")

					# Strip tags
					clean_content = re.sub(r"<SOVEREIGN_LOG>.*?</SOVEREIGN_LOG>", "", content, flags=re.DOTALL).strip()

					# Evitar enviar respuestas de Derecho al Silencio a Telegram
					from red_pill.core.agent_worker import is_silence_response

					if row["channel"] != "system" and clean_content and not is_silence_response(clean_content):
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

	def check_minion_inbox_auto_inject(self, worker: "IDEWorker"):
		conn = worker._get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT cascade_id, updated_at FROM telegram_sessions WHERE cascade_type = 'ghost' ORDER BY updated_at DESC LIMIT 1")
		session_row = cursor.fetchone()
		if not session_row:
			cascade_id = self._client.start_cascade()
			cursor.execute("INSERT INTO telegram_sessions (channel_user_id, cascade_id, cascade_type) VALUES ('system', ?, 'ghost')", (cascade_id,))
			conn.commit()
		else:
			cascade_id = session_row["cascade_id"]

		status = self._client.get_trajectory_status(cascade_id)

		if status == "CASCADE_RUN_STATUS_RUNNING":
			# Circuit Breaker checking
			if session_row:
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
				'<user_rules>\n<RULE[user_global]>\n<constraint critical="true" level="0" name="headless_restriction">\n'
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
			success = self._client.send_user_message(cascade_id, combined)
			if success:
				# Update updated_at for Circuit Breaker
				cursor.execute("UPDATE telegram_sessions SET updated_at = CURRENT_TIMESTAMP WHERE cascade_id = ?", (cascade_id,))
				# GHOST TRACKING: Insert synthetic row to inbox to force checking response
				ghost_id = str(uuid.uuid4())
				cursor.execute(
					"INSERT INTO inbox (message_id, channel, channel_user_id, payload, cascade_id, status) VALUES (?, 'system', 'ghost_cron', '{}', ?, 'WAITING_FOR_RESPONSE')",
					(ghost_id, cascade_id),
				)
				conn.commit()
			else:
				logger.error("Auto-inject failed. Reports were lost from inbox.")
		conn.close()

	def process_cognitive_queue(self, worker: "IDEWorker"):
		conn = worker._get_connection()
		conn.row_factory = sqlite3.Row
		cursor = conn.cursor()

		cursor.execute("SELECT cascade_id, updated_at FROM telegram_sessions WHERE cascade_type = 'ghost' ORDER BY updated_at DESC LIMIT 1")
		session_row = cursor.fetchone()
		if not session_row:
			conn.close()
			return

		cascade_id = session_row["cascade_id"]
		status = self._client.get_trajectory_status(cascade_id)

		if status == "CASCADE_RUN_STATUS_RUNNING":
			conn.close()
			return

		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		queue_manager = CognitiveQueueManager()
		# Carril cognitivo: solo tareas del DriveEvaluator. Los jobs mecánicos
		# (drivers del Job Manager) los consume el runner shot-and-forget.
		task = queue_manager.pop_next_task(allowed_sources=["drive_evaluator"])

		if not task:
			# El Motor de Voluntad (Lóbulo Frontal) evalúa el entorno si la cola está vacía
			from red_pill.cognitive.drive_evaluator import DriveEvaluator

			evaluator = DriveEvaluator(queue_manager)
			injected = evaluator.evaluate_pulse()

			if injected > 0:
				logger.info(f"[DRIVE] Evaluator injected {injected} new cognitive tasks.")

			conn.close()
			return

		logger.info(f"Processing Cognitive Task: {task['id']} (Priority: {task['priority']})")

		payload_text = json.dumps(task["payload"], indent=2)
		tools_allowed = task["payload"].get("tools_allowed", [])
		run_cmd_permitted = "run_command" in tools_allowed and task["source"] == "drive_evaluator"

		rule_run_cmd = (
			"1. PERMITTED: You may use the `run_command` tool only to execute commands directly required for this task."
			if run_cmd_permitted
			else "1. PROHIBITED: You are STRICTLY FORBIDDEN from using the `run_command` tool. Execution will block and fail."
		)

		from red_pill.core import prompts as core

		prompt = core.render(
			"plugins/antigravity_ide",
			"pulse_cognitive_queue_user",
			rule_run_cmd=rule_run_cmd,
			task_id=task["id"],
			task_source=task["source"],
			payload=payload_text,
		)

		success = self._client.send_user_message(cascade_id, prompt)
		if success:
			cursor.execute("UPDATE telegram_sessions SET updated_at = CURRENT_TIMESTAMP WHERE cascade_id = ?", (cascade_id,))
			ghost_id = str(uuid.uuid4())
			cursor.execute(
				"INSERT INTO inbox (message_id, channel, channel_user_id, payload, cascade_id, status) VALUES (?, 'system', 'ghost_cognitive', '{}', ?, 'WAITING_FOR_RESPONSE')",
				(ghost_id, cascade_id),
			)
			conn.commit()
		else:
			logger.error(f"Failed to inject cognitive task {task['id']}")
			queue_manager.mark_failed(task["id"], "Failed to send message to Ghost Cascade")

		conn.close()

	# ── agy path ─────────────────────────────────────────────────────────────

	def check_minion_inbox_auto_inject_agy(self, worker: "IDEWorker"):
		if not self._bridge_minion:
			return
		activity_file = Path(os.environ.get("HOME", "")) / ".gemini" / "antigravity" / "activity_tracker"
		if activity_file.exists():
			import time

			if time.time() - activity_file.stat().st_mtime < 300:  # 5 minutes threshold
				return

		from red_pill.core.inbox import MinionInbox

		inbox = MinionInbox()
		unread = inbox.pop_unread(limit=5)

		if unread:
			logger.info(f"[Agy] Auto-injecting {len(unread)} unread minion reports synchronously")
			prompts = [
				'<user_rules>\n<RULE[user_global]>\n<constraint critical="true" level="0" name="headless_restriction">\n'
				"[SYSTEM: HEADLESS INBOX INJECTION]\n"
				"1. PERMITTED: Use MCP RedPill-Kernel tools for memory consolidation and DB queries.\n"
				"</constraint>\n</RULE[user_global]>\n</user_rules>\n\n"
				"[SYSTEM AUTO-INJECT: Minion Background Reports]"
			]
			for r in unread:
				prompts.append(f"Source: {r['source']}\nStatus: {r['status']}\nEvent ID: {r['event_id']}\nContent: {r['content']}")

			combined = "\n\n".join(prompts)
			worker._touch_lease()
			result = self._bridge_minion.prompt(combined, timeout=300)
			if result.ok:
				logger.info("[Agy] Successfully processed minion reports")
			else:
				logger.error(f"[Agy] Failed to process minion reports: {result.error}")

	def process_cognitive_queue_agy(self, worker: "IDEWorker"):
		if not self._bridge_minion:
			return
		from red_pill.cognitive.queue_manager import CognitiveQueueManager

		queue_manager = CognitiveQueueManager()
		# Carril cognitivo: ver process_cognitive_queue — mismo aislamiento.
		task = queue_manager.pop_next_task(allowed_sources=["drive_evaluator"])

		if not task:
			from red_pill.cognitive.drive_evaluator import DriveEvaluator

			evaluator = DriveEvaluator(queue_manager)
			injected = evaluator.evaluate_pulse()
			if injected > 0:
				logger.info(f"[DRIVE] Evaluator injected {injected} new cognitive tasks.")
			return

		logger.info(f"[Agy] Processing Cognitive Task: {task['id']} (Priority: {task['priority']})")
		payload_text = json.dumps(task["payload"], indent=2)

		from red_pill.core import prompts as core

		prompt = core.render(
			"plugins/antigravity_ide",
			"pulse_cognitive_agy_user",
			task_id=task["id"],
			task_source=task["source"],
			payload=payload_text,
		)

		worker._touch_lease()
		result = self._bridge_minion.prompt(prompt, timeout=600)
		if result.ok:
			logger.info(f"[Agy] Cognitive task {task['id']} completed successfully")
			queue_manager.mark_completed(task["id"])
		else:
			logger.error(f"[Agy] Cognitive task {task['id']} failed: {result.error}")
			queue_manager.mark_failed(task["id"], result.error or "Empty response")


def build_antigravity_pulse_strategy(context: "PulseContext") -> Optional[AntigravityPulseStrategy]:
	"""Strategy factory: declines (None) when no bridge needs Antigravity, so a
	worker served by other backends never builds the IDE client."""
	if not AntigravityPulseStrategy.applies(context.capabilities):
		return None
	return AntigravityPulseStrategy(context.bridge_minion)


def _register() -> None:
	"""Self-register this backend's strategy with the core registry. Imported
	by the core's discovery (`red_pill.core.pulse_strategy`), never hardcoded."""
	from red_pill.core.pulse_strategy import register_pulse_strategy

	register_pulse_strategy(build_antigravity_pulse_strategy)


_register()


__all__ = ["AntigravityPulseStrategy", "build_antigravity_pulse_strategy"]
