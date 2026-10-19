"""Inject red-pill into Claude Code.

Handles: anchor blocks (CLAUDE.md), MCP config, settings.json.
Delegates to the legacy monolithic scripts.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess

logger = logging.getLogger("inject_claude_code")

INJECT_ROOT = os.path.dirname(__file__)
SCRIPTS_ROOT = os.path.join(INJECT_ROOT, "..", "..")

# Nombres legacy (snake_case) renombrados a kebab el 2026-09-10 — nunca se recrean.
_LEGACY_SKILLS = (
	"agent_core",
	"knowledge_access",
	"context_distiller",
	"job_manager",
	"memory_manager",
	"memory_manager_template",
	"minion_delegation",
	"project_anchor_management",
	"skill_creation",
	"sovereign_handshake",
	"swarm_flow_manager",
	"workspace_memory",
)


def _deploy_skills(redpill_dir: str) -> int:
	"""Espeja las skills canónicas en `~/.claude/skills/` como **symlinks kebab**.

	Claude Code no tenía paso de skills en su adaptador: solo se le inyectaban
	anchors/MCP/settings, así que cualquier skill que necesitara quedaba fuera (y
	los residuos snake_case sobrevivían). El estándar es un symlink kebab por
	skill → su copia canónica desplegada (`~/.agent/skills`, genérica, con
	placeholders resueltos; si no, `~/.config/opencode/skills`). Idempotente.
	"""
	import shutil

	home = os.path.expanduser("~")
	dest = os.path.join(home, ".claude", "skills")
	agent = os.path.join(home, ".agent", "skills")
	opencode = os.path.join(home, ".config", "opencode", "skills")

	# Nombres canónicos = fuente de verdad del repo (skills/ + seeds/opencode/skills),
	# unidos a lo ya desplegado (por si el repo corre incompleto).
	names: set[str] = set()
	for root in (
		os.path.join(redpill_dir, "skills"),
		os.path.join(redpill_dir, "seeds", "opencode", "skills"),
		agent,
		opencode,
	):
		if os.path.isdir(root):
			names |= {n for n in os.listdir(root) if os.path.exists(os.path.join(root, n, "SKILL.md"))}

	os.makedirs(dest, exist_ok=True)
	changed = 0

	def _is_ours_link(p: str) -> bool:
		"""Symlink que apunta a una copia canónica que gestionamos (agent/opencode)."""
		if not os.path.islink(p):
			return False
		real = os.path.realpath(p)
		return real.startswith(agent + os.sep) or real.startswith(opencode + os.sep)

	# Poda SOLO de lo nuestro (red-pill es invitado, nunca dueño):
	#  - nombres legacy snake_case (renombrados a kebab el 2026-09-10)
	#  - symlinks creados por nosotros hacia agent/opencode
	# Cualquier entrada ajena (dir o symlink del usuario) se RESPETA.
	for entry in list(os.listdir(dest)):
		p = os.path.join(dest, entry)
		if entry in _LEGACY_SKILLS:
			if os.path.islink(p):
				os.unlink(p)
			elif os.path.isdir(p):
				shutil.rmtree(p)
			changed += 1
		elif _is_ours_link(p):
			# Symlink nuestro: solo se poda si ya NO es una skill canónica.
			# (Si sigue siéndolo, lo actualiza el bucle de creación sin recrear.)
			if entry not in names:
				os.unlink(p)
				changed += 1

	# Symlink kebab → copia canónica desplegada (resuelta). No pisamos contenido ajeno.
	for name in sorted(names):
		if name in _LEGACY_SKILLS:
			continue
		target = None
		for root in (agent, opencode):
			if os.path.exists(os.path.join(root, name, "SKILL.md")):
				target = os.path.join(root, name)
				break
		if not target:
			continue  # aún sin desplegar: convergerá en la próxima pasada
		link = os.path.join(dest, name)
		if os.path.islink(link):
			if os.readlink(link) == target:
				continue
			os.unlink(link)
		elif os.path.exists(link):
			continue  # entrada ajena con nombre canónico: se respeta
		os.symlink(target, link)
		changed += 1

	return changed


def inject(args: argparse.Namespace) -> int:
	redpill_dir = getattr(args, "redpill_dir", None) or os.path.join(INJECT_ROOT, "..", "..", "..")
	redpill_dir = os.path.abspath(redpill_dir)
	uv = getattr(args, "uv_path", None) or "uv"
	changed = 0

	# Anchor blocks → CLAUDE.md
	anchor_script = os.path.join(SCRIPTS_ROOT, "inject_anchor.py")
	if os.path.exists(anchor_script):
		cmd = [uv, "run", "python", anchor_script, "--ide", "claude-code", "--redpill-dir", redpill_dir]
		result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.join(redpill_dir))
		if result.returncode == 0:
			changed += 1
			logger.info(f"  claude-code anchors → {result.stdout.strip().split(chr(10))[-1]}")

	# MCP → .claude.json
	mcp_script = os.path.join(SCRIPTS_ROOT, "inject_mcp.py")
	if os.path.exists(mcp_script):
		uv_path = getattr(args, "uv_path", None) or "uv"
		cmd = [uv, "run", "python", mcp_script, "--uv-path", uv_path, "--redpill-dir", redpill_dir]
		result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.join(redpill_dir))
		if result.returncode == 0:
			changed += 1
			logger.info(f"  claude-code MCP → {result.stdout.strip().split(chr(10))[-1]}")

	# Settings → settings.json
	settings_script = os.path.join(SCRIPTS_ROOT, "inject_settings.py")
	if os.path.exists(settings_script):
		cmd = [uv, "run", "python", settings_script, "--redpill-dir", redpill_dir]
		result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.join(redpill_dir))
		if result.returncode == 0:
			changed += 1
			logger.info(f"  claude-code settings → {result.stdout.strip().split(chr(10))[-1]}")

	# Skills → ~/.claude/skills/ (espejo kebab de las canónicas)
	try:
		n = _deploy_skills(redpill_dir)
		if n:
			changed += 1
		logger.info(f"  claude-code skills → {n} symlink(s)")
	except Exception as exc:  # noqa: BLE001 — nunca tumbar la inyección por skills
		logger.warning(f"  claude-code skills: omitido ({exc})")

	return changed
