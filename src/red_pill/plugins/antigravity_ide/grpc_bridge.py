"""
GrpcBridge — gRPC-Web bridge to Antigravity LanguageServer

NOT @Deprecated — actively used for:
	- Chronicle pipeline: conversation extraction → archive_memories
	- GetAllCascadeTrajectories: list all IDE conversations
	- GetCascadeTrajectorySteps: extract conversation content

For prompt execution (Telegram, AWAKENINGs), use AgyBridge instead.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .bridge import BackendType, BridgeCapabilities, ConversationResult, IDEBridge, NotSupportedError

logger = logging.getLogger(__name__)


class GrpcBridge(IDEBridge):
	"""gRPC-Web bridge to LanguageServer.

	Two roles:
		1. EXECUTION (legacy, limited): start_cascade + send_user_message.
			Subject to approval gates and ghost cascades.
		2. EXTRACTION (active, primary): GetAllCascadeTrajectories +
			GetCascadeTrajectorySteps for Chronicle pipeline.
	"""

	def __init__(self):
		self._client = None

	def _get_client(self):
		"""Lazy-init the IDE client."""
		if self._client is None:
			from .ide_client import AntigravityIDEClient

			self._client = AntigravityIDEClient()
		return self._client

	def get_capabilities(self) -> BridgeCapabilities:
		return BridgeCapabilities(
			backend=BackendType.GRPC,
			auto_approve=False,  # Requires manual approval
			ephemeral_mode=False,  # Creates ghost cascades
			conversation_resume=False,
			model_selection=False,
			mcp_tools=False,  # Tools get stuck in PENDING
		)

	def prompt(self, text: str, *, model: str = "flash", timeout: int = 120) -> ConversationResult:
		"""Start a new cascade and inject a message (legacy gRPC flow).

		Note: This is async — the response must be polled via check_for_replies.
		The ConversationResult.response contains a status marker, not the actual response.
		"""
		try:
			client = self._get_client()
			cascade_id = client.start_cascade()
			client.send_user_message(cascade_id, text)
			return ConversationResult(
				conversation_id=cascade_id,
				response="[ASYNC] Response must be polled via check_for_replies",
			)
		except Exception as e:
			return ConversationResult(
				conversation_id="",
				response="",
				error=str(e),
			)

	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		raise NotSupportedError("Conversation resume is not supported on gRPC backend. Use AgyBridge (IDE_BACKEND=agy) for this feature.")

	def health_check(self) -> bool:
		"""Check if the LanguageServer is reachable."""
		try:
			client = self._get_client()
			return client.connected
		except Exception:
			return False

	# --- Extraction (Chronicle pipeline) — ACTIVE USE ---

	def get_all_trajectories(self) -> List[Dict[str, Any]]:
		"""List all conversation summaries from the IDE.

		Used by Chronicle to discover new conversations for archive ingestion.
		Returns a list of trajectory summary dicts with keys:
			cascade_id, status, summary, lastModifiedTime, etc.
		"""
		try:
			client = self._get_client()
			import requests

			resp = requests.post(
				client._url("GetAllCascadeTrajectories"),
				headers=client._get_headers(),
				json={},
				verify=False,
			)
			if resp.status_code == 200:
				data = resp.json()
				summaries = data.get("trajectorySummaries", {})
				result = []
				for cid, traj in summaries.items():
					result.append(
						{
							"cascade_id": cid,
							"status": traj.get("status", "UNKNOWN"),
							"summary": traj.get("summary", ""),
							"lastModifiedTime": traj.get("lastModifiedTime", ""),
						}
					)
				return result
			logger.error(f"Failed to get trajectories: {resp.status_code}")
			return []
		except Exception as e:
			logger.error(f"[GrpcBridge] get_all_trajectories failed: {e}")
			return []

	def get_trajectory_steps(self, cascade_id: str, start_index: int = 0, end_index: int = 1000) -> List[Dict[str, Any]]:
		"""Extract all steps from a conversation. Used by Chronicle.

		Returns a list of step dicts with the raw content from the IDE.
		"""
		try:
			client = self._get_client()
			return client.get_cascade_trajectory_steps(cascade_id, start_index, end_index)
		except Exception as e:
			logger.error(f"[GrpcBridge] get_trajectory_steps failed: {e}")
			return []
