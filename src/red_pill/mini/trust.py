"""Trust boundaries for the mini harness.

The mini bodies are local, but their inputs are not all equally trusted: a job
payload can come from an agent, so workspace/DB/socket/URL and identity must be
bounded before the bridge sees them. This module centralizes that policy.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

from red_pill.core.paths import get_workspace_root, get_worktrees_root


class MiniTrustError(ValueError):
	"""A mini input escaped the local trust boundary."""


def _workspace_roots() -> list[Path]:
	raw = os.getenv("MINI_WORKSPACE_ROOTS", "").strip()
	if raw:
		return [Path(item).expanduser().resolve() for item in raw.split(os.pathsep) if item.strip()]
	return [
		get_workspace_root().resolve(),
		get_worktrees_root().resolve(),
		Path(tempfile.gettempdir()).resolve(),
	]


def _under(path: Path, roots: Iterable[Path]) -> bool:
	return any(path == root or root in path.parents for root in roots)


def validate_workspace(path: str) -> str:
	"""Resolve a workspace and require it under an allowed local root."""
	raw = str(path or "").strip()
	if not raw:
		raise MiniTrustError("workspace required")
	resolved = Path(raw).expanduser().resolve()
	if not resolved.is_dir():
		raise MiniTrustError(f"workspace does not exist: {raw}")
	if not _under(resolved, _workspace_roots()):
		raise MiniTrustError(f"workspace outside allowed roots: {resolved}")
	return str(resolved)


def validate_db_path(path: Optional[str]) -> Optional[str]:
	"""Allow the live session DB or an ephemeral test DB, never an arbitrary file."""
	if path is None or not str(path).strip():
		return None
	raw = str(path).strip()
	if raw == ":memory:":
		return raw
	resolved = Path(raw).expanduser().resolve()
	allowed = [Path(tempfile.gettempdir()).resolve()]
	try:
		from red_pill.core.paths import get_data_dir

		allowed.append(Path(get_data_dir()).resolve())
	except Exception:
		pass
	if not _under(resolved, allowed):
		raise MiniTrustError(f"db_path outside allowed roots: {resolved}")
	return str(resolved)


def validate_socket_path(path: Optional[str]) -> Optional[str]:
	"""Allow a Unix socket under the runtime dir or the ephemeral test root."""
	if path is None or not str(path).strip():
		return None
	resolved = Path(str(path)).expanduser().resolve()
	if not resolved.is_absolute():
		raise MiniTrustError(f"socket path must be absolute: {path}")
	allowed = [Path(tempfile.gettempdir()).resolve()]
	runtime = os.getenv("XDG_RUNTIME_DIR")
	if runtime:
		allowed.append(Path(runtime).resolve())
	if not _under(resolved, allowed):
		raise MiniTrustError(f"socket outside allowed roots: {resolved}")
	return str(resolved)


def validate_loopback_url(url: Optional[str]) -> Optional[str]:
	"""FLM is local-only in v0; never allow the model URL to exfiltrate history."""
	if url is None or not str(url).strip():
		return None
	parsed = urlparse(str(url).strip())
	if parsed.scheme not in ("http", "https"):
		raise MiniTrustError(f"unsupported FLM scheme: {parsed.scheme!r}")
	if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
		raise MiniTrustError(f"FLM URL must be loopback: {parsed.hostname!r}")
	if parsed.username or parsed.password:
		raise MiniTrustError("FLM URL must not carry credentials")
	return str(url).strip()


def validate_profile(profile: Optional[str]) -> str:
	name = str(profile or "").strip().lower()
	from red_pill.mini.profiles import PROFILES

	if name not in PROFILES:
		raise MiniTrustError(f"unknown mini profile: {profile!r}")
	return name


def normalize_local_mini_payload(payload: Dict[str, Any], session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
	"""Sanitize an MCP `job_submit` payload for `backend=local-mini`.

	The caller's identity wins; a payload may not choose another soul, DB,
	socket or FLM URL. Direct queue callers (tests/E2E) bypass this and are
	validated separately by the bridge/driver.
	"""
	out = dict(payload)
	out["profile"] = validate_profile(out.get("profile"))
	requested_cid = str(out.get("continuity_id") or "").strip() or None
	trusted_cid = str((session or {}).get("continuity_id") or "").strip() or None
	if requested_cid and trusted_cid and requested_cid != trusted_cid:
		raise MiniTrustError("continuity_id does not belong to the calling session")
	out["continuity_id"] = trusted_cid
	if not trusted_cid:
		out.pop("continuity_id", None)
	trusted_mission = str((session or {}).get("mission_id") or "").strip() or None
	requested_mission = str(out.get("mission_id") or "").strip() or None
	if requested_mission and trusted_mission and requested_mission != trusted_mission:
		raise MiniTrustError("mission_id does not belong to the calling session")
	if trusted_mission:
		out["mission_id"] = trusted_mission
	out.pop("originator", None)
	out.pop("db_path", None)
	out.pop("gpu_socket", None)
	out.pop("flm_url", None)
	for key in ("workspace", "cwd"):
		if out.get(key):
			out[key] = validate_workspace(str(out[key]))
	return out
