"""Detect the installed OpenCode version and pick the matching seed.

V1 (``1.x``) and V2 (``2.x``) share the ``opencode`` command and
``~/.config/opencode`` but use incompatible config schemas.  The injector must
seed the schema the *running* OpenCode understands, so this module probes the
host and resolves a versioned seed.

Detection priority (highest first):

1. ``REDPILL_OPENCODE_VERSION`` / ``REDPILL_OPENCODE_MAJOR`` environment override
   (tests, CI, operators pinning a tier explicitly).
2. The ``opencode`` binary in ``PATH`` (``opencode --version``).
3. The desktop ``.deb`` package version (``dpkg-query``), if present.
4. The shape of an existing ``opencode.jsonc`` (already-V2 markers).
5. Default to V1 with a warning (legacy-safe: never silently emit V2 into an
   unknown install).

When several probes disagree, the highest major wins: V2 config is the
forward-compatible target, and a V1 binary that coexists with a V2 desktop is
the operator's transitional state.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("opencode_version")

_SEMVER = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
_CONFIG_DIRS = ("~/.config/opencode", "/etc/opencode")


@dataclass
class OpenCodeInfo:
	installed: bool
	version: tuple[int, int, int] | None
	version_str: str | None
	major: int | None
	source: str

	@property
	def tier(self) -> str:
		return f"v{self.major}" if self.major else "unknown"

	def __str__(self) -> str:
		if not self.installed:
			return "not installed"
		return f"v{self.major or '?'} ({self.version_str or 'unknown'}, via {self.source})"


def parse_version(text: str | None) -> tuple[int, int, int] | None:
	"""Return the first ``X.Y.Z`` in *text* (handles ``opencode v2.1.4``)."""
	if not text:
		return None
	match = _SEMVER.search(text)
	if not match:
		return None
	return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _run(cmd: list[str]) -> str | None:
	if not shutil.which(cmd[0]):
		return None
	try:
		proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
	except (OSError, subprocess.SubprocessError):
		return None
	return (proc.stdout or "") + (proc.stderr or "")


def _probe_cli(binary: str = "opencode") -> tuple[tuple[int, int, int] | None, str | None]:
	out = _run([binary, "--version"])
	return parse_version(out), (out.strip().splitlines()[0] if out and out.strip() else None)


def _probe_dpkg() -> tuple[tuple[int, int, int] | None, str | None]:
	out = _run(["dpkg-query", "-W", "-f=${Version}", "opencode"])
	return parse_version(out), (out.strip() if out and out.strip() else None)


def config_is_v2(cfg: dict) -> bool:
	"""Heuristic: does this config already use V2-only shapes?"""
	if not isinstance(cfg, dict):
		return False
	if any(key in cfg for key in ("plugins", "permissions", "providers")):
		return True
	mcp = cfg.get("mcp")
	return isinstance(mcp, dict) and "servers" in mcp


def _probe_config(config_path: str | None) -> bool:
	if not config_path or not os.path.isfile(config_path):
		return False
	try:
		import sys

		sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
		from _config_common import strip_jsonc_comments
		from migrate_opencode_v2 import _strip_trailing_commas

		raw = open(config_path, encoding="utf-8").read()
		cfg = json.loads(_strip_trailing_commas(strip_jsonc_comments(raw)))
	except Exception:
		return False
	return config_is_v2(cfg)


def _config_dir_present() -> str | None:
	for candidate in _CONFIG_DIRS:
		expanded = os.path.expanduser(candidate)
		if os.path.isdir(expanded):
			return expanded
	return None


def detect_info(config_path: str | None = None, binary: str = "opencode") -> OpenCodeInfo:
	"""Probe the host and return the best-known OpenCode version."""
	# 1. Explicit override.
	env_version = parse_version(os.environ.get("REDPILL_OPENCODE_VERSION"))
	env_major = os.environ.get("REDPILL_OPENCODE_MAJOR")
	if env_version or env_major:
		if not env_version and env_major and env_major.isdigit():
			env_version = (int(env_major), 0, 0)
		if env_version:
			return OpenCodeInfo(True, env_version, ".".join(map(str, env_version)), env_version[0], "env")

	# 2-3. CLI and desktop probes; highest major wins.
	candidates: list[tuple[tuple[int, int, int], str]] = []
	cli_version, cli_raw = _probe_cli(binary)
	if cli_version:
		candidates.append((cli_version, "cli"))
	dpkg_version, dpkg_raw = _probe_dpkg()
	if dpkg_version:
		candidates.append((dpkg_version, "dpkg"))

	installed = _config_dir_present() is not None or bool(candidates)

	if candidates:
		version, source = max(candidates, key=lambda item: item[0])
		raw = cli_raw if source == "cli" else dpkg_raw
		return OpenCodeInfo(True, version, raw, version[0], source)

	# 4. Existing config shape.
	if _probe_config(config_path):
		return OpenCodeInfo(True, (2, 0, 0), "2.0.0 (config)", 2, "config")

	if installed:
		logger.warning("OpenCode installed but its version could not be detected; defaulting to V1 seeds.")
		return OpenCodeInfo(True, None, None, 1, "default")

	return OpenCodeInfo(False, None, None, None, "none")


def select_config_seed(seeds_root: str, major: int | None) -> str | None:
	"""Resolve the versioned config seed.

	Supports both layouts so new versions need no code change:
	``settings/v{major}/opencode.jsonc``, ``settings/opencode.v{major}.jsonc``,
	then the flat legacy ``settings/opencode.jsonc``.
	"""
	settings = os.path.join(seeds_root, "settings")
	if major is not None:
		candidates = [
			os.path.join(settings, f"v{major}", "opencode.jsonc"),
			os.path.join(settings, f"opencode.v{major}.jsonc"),
		]
		for candidate in candidates:
			if os.path.isfile(candidate):
				return candidate
	flat = os.path.join(settings, "opencode.jsonc")
	return flat if os.path.isfile(flat) else None


def needs_v1_plugin_pin(major: int | None) -> bool:
	"""V1 plugins import ``@opencode-ai/plugin``; V2 plugins do not need it."""
	return (major or 1) < 2


def requires_config_migration(major: int | None) -> bool:
	"""V2 must not inherit V1 ``plugin``/``mcp.<name>``/``permission`` keys."""
	return (major or 1) >= 2
