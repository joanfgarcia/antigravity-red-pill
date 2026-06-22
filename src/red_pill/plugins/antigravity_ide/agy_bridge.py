"""
AgyBridge — Execution backend using agy CLI (Antigravity >= 2.0)

Uses `agy -p --dangerously-skip-permissions` for headless, auto-approved
prompt execution. No API key needed — uses ANTIGRAVITY_LS_ADDRESS +
ANTIGRAVITY_CSRF_TOKEN from the local IDE session.

Multi-turn support via `agy --conversation <uuid> -p`:
	- First message: dir-diff captures the conversation UUID
	- Subsequent: `--conversation <uuid>` resumes, prefix-strip extracts delta

Requirements:
	- agy CLI installed (>= 1.0)
	- Antigravity IDE running (language_server process active)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid as uuid_mod
from pathlib import Path
from typing import Optional, Set, Tuple

from red_pill.core.paths import get_bunker_root
from red_pill.swarm.bridges.base import AgentBridge, BackendType, BridgeCapabilities, ConversationResult

logger = logging.getLogger(__name__)


def _get_brain_dir() -> Optional[Path]:
	"""Find the active agy brain directory."""
	from red_pill.core.paths import get_antigravity_brain_dir

	# Primary: canonical path from paths.py
	canonical = get_antigravity_brain_dir()
	if canonical.is_dir():
		return canonical
	# Legacy fallback: antigravity-cli
	legacy = Path.home() / ".gemini" / "antigravity-cli" / "brain"
	if legacy.is_dir():
		return legacy
	return None


def _snapshot_brain(brain_dir: Path) -> Set[str]:
	"""Get the set of conversation UUIDs in the brain directory."""
	try:
		return {d.name for d in brain_dir.iterdir() if d.is_dir()}
	except Exception:
		return set()


class AgyBridge(AgentBridge):
	"""Backend v2: agy CLI with --dangerously-skip-permissions.

	Supports:
		- One-shot prompts (ephemeral, no ghost cascades)
		- Multi-turn via --conversation <uuid> (dir-diff UUID capture)
		- Auto-approval of all tool calls
		- MCP tool usage within the agent
	"""

	AGY_BIN = "agy"

	def __init__(self, agy_path: Optional[str] = None):
		self._agy_path = agy_path or shutil.which(self.AGY_BIN)
		if not self._agy_path:
			raise RuntimeError(
				"Antigravity CLI (agy) not found in PATH. "
				"Neon-Link command execution and autonomous AWAKENINGs require agy >= 1.0. "
				"Install: curl -fsSL https://antigravity.google/cli/install.sh | bash"
			)

	def _get_env(self) -> dict:
		"""Build env dict with LS_ADDRESS and CSRF_TOKEN.

		If running inside the IDE, these are already set as env vars.
		If running externally (systemd timer, cron), discover from running processes.
		"""
		env = os.environ.copy()
		if "ANTIGRAVITY_LS_ADDRESS" not in env:
			try:
				addr, token = self._discover_ls()
				env["ANTIGRAVITY_LS_ADDRESS"] = addr
				env["ANTIGRAVITY_CSRF_TOKEN"] = token
			except Exception as e:
				logger.error(f"Failed to discover LanguageServer: {e}")
				raise RuntimeError(
					"Cannot discover Antigravity IDE session. Ensure the IDE is running or set ANTIGRAVITY_LS_ADDRESS and ANTIGRAVITY_CSRF_TOKEN."
				) from e
		return env

	def _discover_ls(self) -> Tuple[str, str]:
		"""Discover language_server address and CSRF token from running processes."""
		from red_pill.utils.antigravity_history.discovery import discover_language_servers, find_all_endpoints

		servers = discover_language_servers()
		if not servers:
			raise RuntimeError("No Antigravity IDE LanguageServers found.")
		endpoints = find_all_endpoints(servers)
		if not endpoints:
			raise RuntimeError("No valid IDE endpoints discovered.")
		ep = endpoints[0]
		return f"localhost:{ep['port']}", ep["csrf"]

	def _run_agy(self, args: list, timeout: int) -> str:
		"""Execute agy CLI with common flags."""
		cmd = [
			self._agy_path,
			*args,
			"--dangerously-skip-permissions",
			"--print-timeout",
			f"{timeout}s",
		]
		logger.debug(f"[AgyBridge] Running: {' '.join(cmd[:4])}... (timeout={timeout}s)")
		try:
			result = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				timeout=timeout + 10,
				env=self._get_env(),
				cwd=str(get_bunker_root().parent),
			)
		except subprocess.TimeoutExpired as e:
			logger.error(f"[AgyBridge] Command timed out after {timeout + 10}s")
			raise RuntimeError(f"agy timed out after {timeout}s") from e

		if result.returncode != 0:
			stderr = result.stderr.strip()
			logger.error(f"[AgyBridge] agy failed (rc={result.returncode}): {stderr}")
			raise RuntimeError(f"agy failed (rc={result.returncode}): {stderr}")

		stdout = result.stdout.strip()
		stderr = result.stderr.strip()

		# Log stderr even on success for diagnostics
		if stderr:
			logger.warning(f"[AgyBridge] agy stderr (rc=0): {stderr[:500]}")

		# Empty response with stderr hints at a silent failure
		if not stdout and stderr:
			logger.error(f"[AgyBridge] agy returned empty stdout with stderr: {stderr[:500]}")
			raise RuntimeError(f"agy returned empty response: {stderr[:200]}")

		return stdout

	def get_capabilities(self) -> BridgeCapabilities:
		return BridgeCapabilities(
			backend=BackendType.AGY,
			auto_approve=True,
			ephemeral_mode=True,
			conversation_resume=True,
			model_selection=True,
			mcp_tools=True,
		)

	def prompt(
		self,
		text: str,
		*,
		model: str = "flash",
		effort: Optional[str] = None,
		cwd: Optional[str] = None,
		timeout: int = 300,
	) -> ConversationResult:
		"""Send a one-shot prompt via agy -p.

		Uses dir-diff to capture the conversation UUID for future multi-turn.
		Embeds an eid (ephemeral ID) in the prompt as safety net for UUID verification.

		effort/cwd: accepted for interface parity. MAPPING is AgyBridge's job (TODO-wire):
		agy fuses model+mode in the selectable model name (`agy models`):
			Gemini 3.5 Flash (Low|Medium|High) · Gemini 3.1 Pro (Low|High) ·
			Claude Sonnet 4.6 (Thinking) · Claude Opus 4.6 (Thinking) · GPT-OSS 120B (Medium).
		So the portable (model, effort) → `agy --model "Base (Mode)"` (Claude variants have only
		"(Thinking)" → effort ignored). Wire when agy becomes an active swarm backend; today agy
		is not the initial backend, so this stays documented (current behavior: no --model).
		"""
		eid = f"eid:{uuid_mod.uuid4().hex[:12]}"
		tagged_text = f"{text}\n<!-- {eid} -->"

		brain_dir = _get_brain_dir()
		before = _snapshot_brain(brain_dir) if brain_dir else set()

		try:
			response = self._run_agy(["-p", tagged_text], timeout)
		except Exception as e:
			return ConversationResult(
				conversation_id="",
				response="",
				error=str(e),
			)

		# Capture conversation UUID via dir-diff
		conversation_id = ""
		if brain_dir:
			after = _snapshot_brain(brain_dir)
			new_dirs = after - before
			if len(new_dirs) == 1:
				conversation_id = new_dirs.pop()
			elif len(new_dirs) > 1:
				# Safety net: verify eid in transcript.jsonl
				conversation_id = self._find_by_eid(brain_dir, new_dirs, eid)
			# else: len == 0 → conversation reused or brain dir not found

		logger.info(f"[AgyBridge] prompt() → conv={conversation_id}, response_len={len(response)}")

		return ConversationResult(
			conversation_id=conversation_id,
			response=response,
			model=model,
		)

	def continue_conversation(
		self,
		text: str,
		*,
		conversation_id: str = "",
		previous_response_len: int = 0,
		timeout: int = 300,
	) -> ConversationResult:
		"""Continue an existing conversation via agy --conversation <uuid> -p.

		Since agy --conversation accumulates ALL previous responses in stdout,
		we use previous_response_len to strip the prefix and extract only the
		new response (delta).

		Args:
			text: The new prompt.
			conversation_id: UUID from the first prompt() call.
			previous_response_len: Length of the accumulated stdout from previous turns.
			timeout: Execution timeout in seconds.
		"""
		if not conversation_id:
			# No session to continue — fallback to new prompt
			logger.warning("[AgyBridge] continue_conversation called without conversation_id, falling back to prompt()")
			return self.prompt(text, timeout=timeout)

		try:
			accumulated = self._run_agy(["--conversation", conversation_id, "-p", text], timeout)
		except Exception as e:
			return ConversationResult(
				conversation_id=conversation_id,
				response="",
				error=str(e),
			)

		# Prefix-strip: extract only the new response
		if previous_response_len > 0 and len(accumulated) > previous_response_len:
			delta = accumulated[previous_response_len:].strip()
		else:
			delta = accumulated.strip()

		logger.info(f"[AgyBridge] continue_conversation() → conv={conversation_id}, accumulated={len(accumulated)}, delta={len(delta)}")

		return ConversationResult(
			conversation_id=conversation_id,
			response=delta,
			# Store accumulated length for next turn
			accumulated_len=len(accumulated),
		)

	def _find_by_eid(self, brain_dir: Path, candidates: Set[str], eid: str) -> str:
		"""Safety net: find the conversation containing our eid marker."""
		for cid in candidates:
			transcript = brain_dir / cid / ".system_generated" / "logs" / "transcript.jsonl"
			if transcript.exists():
				try:
					content = transcript.read_text(encoding="utf-8", errors="ignore")
					if eid in content:
						logger.info(f"[AgyBridge] eid verification matched: {cid}")
						return cid
				except Exception:
					continue
		logger.warning(f"[AgyBridge] eid verification failed for {len(candidates)} candidates")
		return candidates.pop() if candidates else ""

	def health_check(self) -> bool:
		"""Quick connectivity test — sends a minimal prompt."""
		try:
			result = self.prompt("Responde SOLO: OK", timeout=30)
			return result.ok and "OK" in result.response
		except Exception:
			return False
