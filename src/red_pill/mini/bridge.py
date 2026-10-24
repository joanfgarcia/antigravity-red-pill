"""`MiniLocalBridge` — AgentBridge adapter over MiniSession.

Any caller that already speaks `AgentBridge` (agentic jobs, DAG stages, swarm
minions) can use `backend="local-mini"` and get the canonical mirror, profiles,
toolboxes and body migration without a second tool loop.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import red_pill.config as cfg
from red_pill.mini.contracts import ChatProvider
from red_pill.mini.profiles import PROFILES
from red_pill.mini.providers import HTTPProvider, UnixHTTPProvider
from red_pill.mini.session import MiniConfig, MiniSession
from red_pill.mini.tools import WorkspaceTools
from red_pill.mini.trust import validate_db_path, validate_loopback_url, validate_profile, validate_socket_path, validate_workspace
from red_pill.swarm.bridges.base import AgentBridge, BackendType, BridgeCapabilities, ConversationResult

logger = logging.getLogger(__name__)


class MiniLocalBridge(AgentBridge):
	"""Bridge over `MiniSession`: history lives in the mirror, not in a native id."""

	def __init__(
		self,
		*,
		profile: str = "forge",
		continuity_id: Optional[str] = None,
		mission_id: str = "mission:mini-job",
		workspace: Optional[str] = None,
		db_path: Optional[str] = None,
		gpu_socket: Optional[str] = None,
		flm_url: Optional[str] = None,
		operator: str = "Joan",
		origin: Optional[str] = None,
		run_ref: Optional[str] = None,
		lineage_id: Optional[str] = None,
		providers: Optional[Dict[str, ChatProvider]] = None,
		toolboxes: Optional[Dict[str, Any]] = None,
	):
		self.profile = validate_profile(profile)
		self.workspace = validate_workspace(str(workspace or os.getcwd()))
		db_path = validate_db_path(db_path)
		gpu_socket = validate_socket_path(gpu_socket)
		flm_url = validate_loopback_url(flm_url)
		app_cfg = cfg.get_config()
		self._providers = dict(providers or {})
		if not self._providers:
			gpu = validate_socket_path(str(gpu_socket or getattr(app_cfg, "MINI_FORGE_SOCKET", "") or "")) or ""
			flm = validate_loopback_url(str(flm_url or getattr(app_cfg, "MINI_FLM_URL", "http://127.0.0.1:52625"))) or ""
			self._providers = {
				"forge": UnixHTTPProvider(gpu, timeout=300),
				"loom": HTTPProvider(flm, timeout=360),
			}
		self._toolboxes = dict(
			toolboxes
			or {
				"workspace": WorkspaceTools(self.workspace),
				"workspace_ro": WorkspaceTools(self.workspace, read_only=True),
			}
		)
		self._session = MiniSession(
			MiniConfig(
				workspace=self.workspace,
				continuity_id=continuity_id,
				mission_id=mission_id,
				db_path=db_path,
				run_ref=run_ref,
				lineage_id=lineage_id,
				affinity=[mission_id if mission_id.startswith("mission:") else f"mission:{mission_id}"],
				operator=operator,
			),
			self._providers,
			profiles=PROFILES,
			toolboxes=self._toolboxes,
		)

	@property
	def continuity_id(self) -> str:
		return self._session.continuity_id

	def get_capabilities(self) -> BridgeCapabilities:
		return BridgeCapabilities(
			backend=BackendType.LOCAL,
			auto_approve=True,
			ephemeral_mode=False,
			conversation_resume=True,
			model_selection=False,
			mcp_tools=False,
		)

	def health_check(self) -> bool:
		profile = PROFILES[self.profile]
		provider = self._providers.get(profile.provider)
		check = getattr(provider, "health", None)
		if callable(check):
			try:
				return bool(check())
			except Exception:
				return False
		return provider is not None

	def prompt(
		self,
		text: str,
		*,
		model: str = "flash",
		effort: Optional[str] = None,
		cwd: Optional[str] = None,
		timeout: int = 300,
	) -> ConversationResult:
		try:
			result = self._session.run_profile(self.profile, text, timeout=timeout)
		except Exception as e:
			logger.warning(f"[MiniLocalBridge] {self.profile} failed: {e}")
			return ConversationResult(conversation_id=self.continuity_id, response="", error=str(e))
		answer = str(result.get("text") or "")
		if not answer.strip():
			return ConversationResult(
				conversation_id=self.continuity_id,
				response="",
				error="mini body returned an empty answer",
				model=self.profile,
			)
		return ConversationResult(
			conversation_id=self.continuity_id,
			response=answer,
			model=self.profile,
		)

	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		# The mirror is the history; the native conversation_id is irrelevant.
		return self.prompt(text, timeout=timeout)
