"""Detect the installed OpenCode version and resolve the V2 seed.

Red Pill only supports **OpenCode v2** (decision: 2026-10-27). V1 is *migratable*,
never seeded: if the host still has a V1 ``opencode.jsonc``, the injector migrates
it in place (``scripts/migrate_opencode_v2.py``) **before** merging the V2 seed.
A future v3 is **not** assumed compatible — it will need its own verification
before red-pill re-seeds anything.

Detection is explicit and ordered; nothing is inferred from the shape of an
existing config:

1. ``REDPILL_OPENCODE_VERSION`` / ``REDPILL_OPENCODE_MAJOR`` environment override
	(tests, CI, operators pinning a tier explicitly).
2. The ``opencode`` binary in ``PATH`` (``opencode --version``) — the binary that
	will actually run.
3. The desktop ``.deb`` package version (``dpkg-query``), if present.

Contract (`support_error` decides for every caller — install, update, inject):

- **not installed** → nothing to seed; the caller skips OpenCode (``None``).
- **exactly v2** → seeding allowed.
- **v1, v3+, or version that cannot be established** → abort with an explicit
	message. An undetectable tier is ``major=None`` and is an ERROR, never a
	default.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("opencode_version")

#: Única versión sembrable hoy. No se asume compatibilidad hacia adelante.
SUPPORTED_MAJOR = 2
INSTALL_URL = "https://opencode.ai/v2/install"
MIGRATE_HINT = "python3 scripts/migrate_opencode_v2.py --backup"
V1_PLUGIN_PACKAGE = "@opencode-ai/plugin"

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


def _config_dir_present() -> str | None:
	for candidate in _CONFIG_DIRS:
		expanded = os.path.expanduser(candidate)
		if os.path.isdir(expanded):
			return expanded
	return None


def detect_info(binary: str = "opencode") -> OpenCodeInfo:
	"""Probe the host and return the best-known OpenCode version.

	``major`` is ``None`` when the version could not be established: callers must
	treat that as an abort (``support_error``), not as a default tier.
	"""
	# 1. Explicit override.
	env_version = parse_version(os.environ.get("REDPILL_OPENCODE_VERSION"))
	env_major = os.environ.get("REDPILL_OPENCODE_MAJOR")
	if env_version or env_major:
		if not env_version and env_major and env_major.isdigit():
			env_version = (int(env_major), 0, 0)
		if env_version:
			return OpenCodeInfo(True, env_version, ".".join(map(str, env_version)), env_version[0], "env")

	# 2-3. CLI and desktop probes. They must agree on the major: two different
	# majors mean a transitional host (a v1 binary next to a v2 desktop) and
	# picking the highest would be an assumption. Disagreement → undetermined.
	cli_version, cli_raw = _probe_cli(binary)
	dpkg_version, dpkg_raw = _probe_dpkg()
	config_present = _config_dir_present()

	if cli_version and dpkg_version and cli_version[0] != dpkg_version[0]:
		logger.warning(
			"OpenCode: la CLI dice v%s y el paquete .deb v%s; no se puede fijar la versión.",
			cli_version[0],
			dpkg_version[0],
		)
		return OpenCodeInfo(True, None, cli_raw or dpkg_raw, None, "conflict")

	if cli_version:
		return OpenCodeInfo(True, cli_version, cli_raw, cli_version[0], "cli")
	if dpkg_version:
		return OpenCodeInfo(True, dpkg_version, dpkg_raw, dpkg_version[0], "dpkg")

	installed = config_present is not None
	return OpenCodeInfo(installed, None, None, None, "none" if not installed else "undetected")


def support_error(info: OpenCodeInfo) -> str | None:
	"""``None`` si la instalación es sembrable; mensaje de aborto si no.

	Único punto de verdad del contrato: instaladores, `precheck` de inject_cli y
	los injectores deciden con esto, así que el mensaje al usuario no diverge.
	"""
	if not info.installed:
		return None  # No hay OpenCode: no hay nada que sembrar (el caller lo omite).
	if info.major is None:
		return (
			"No se ha podido determinar la versión de OpenCode instalada "
			f"(detección: {info}). Red Pill sólo siembra OpenCode v2 y no se asume "
			"compatibilidad con versiones desconocidas. Comprueba qué binario se está "
			"usando (`which -a opencode` y `opencode --version`), o fija la versión "
			"explícitamente con REDPILL_OPENCODE_VERSION. Nada se ha modificado."
		)
	if info.major < SUPPORTED_MAJOR:
		return (
			f"OpenCode {info} detectado. Red Pill ya NO es compatible con OpenCode v1: "
			"v1 sólo se facilita como MIGRACIÓN de una config existente, nunca se "
			f"siembra sobre él. Actualiza a v2 ({INSTALL_URL}) y vuelve a ejecutar; "
			f"si quieres conservar tu config, migra primero con `{MIGRATE_HINT}`. "
			"Nada se ha modificado."
		)
	if info.major > SUPPORTED_MAJOR:
		return (
			f"OpenCode {info} detectado. Red Pill sólo está validado con OpenCode v2: "
			"una versión mayor nueva no se asume compatible y necesita su propia "
			"verificación antes de resembrar. Usa OpenCode v2 o retira OpenCode de "
			"esta máquina. Nada se ha modificado."
		)
	return None


def select_config_seed(seeds_root: str) -> str | None:
	"""Ruta del seed de config de OpenCode v2 (``settings/v2/opencode.jsonc``).

	Sin layouts heredados: sólo existe el seed de la versión soportada.
	"""
	candidate = os.path.join(seeds_root, "settings", f"v{SUPPORTED_MAJOR}", "opencode.jsonc")
	return candidate if os.path.isfile(candidate) else None
