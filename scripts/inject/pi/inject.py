"""Inject red-pill configuration into Pi (pi-coding-agent).

Pi does NOT support MCP: the Búnker bridge is a TS extension
(`seeds/pi/extensions/red-pill.ts`) that invokes the red-pill CLI via `uv run`
from the checkout. Skills are copied into `~/.pi/agent/skills/` (single merged
dir: generic `skills/` first, then `seeds/pi/skills/` overrides win), which Pi
auto-discovers. Legacy snake_case skill dirs (renamed to kebab-case 2026-09-10)
are pruned so a reseed converges and is idempotent.

Never touches `~/.pi/agent/settings.json` (provider/models belong to the
operator) and never configures MCP.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys

logger = logging.getLogger("inject_pi")

sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "..")))
from _config_common import LEGACY_SKILL_DIRS, build_vars, subst  # noqa: E402


def _pi_agent_dir() -> str:
	return os.path.expanduser("~/.pi/agent")


def _read_seed(path: str) -> str:
	with open(path, encoding="utf-8") as f:
		return f.read()


def _deploy_skills(src_dir: str, dest_dir: str, variables: dict, backup: bool) -> int:
	"""Copy a skills dir into the Pi skills root. Returns number of changed skills."""
	changed = 0
	if not os.path.isdir(src_dir):
		return 0
	os.makedirs(dest_dir, exist_ok=True)
	for skill_entry in sorted(os.listdir(src_dir)):
		skill_src = os.path.join(src_dir, skill_entry)
		skill_md = os.path.join(skill_src, "SKILL.md")
		if not os.path.isdir(skill_src) or not os.path.exists(skill_md):
			continue
		skill_dest_dir = os.path.join(dest_dir, skill_entry)
		os.makedirs(skill_dest_dir, exist_ok=True)
		skill_changed = 0
		for root, dirs, files in os.walk(skill_src):
			dirs[:] = [d for d in dirs if d != "__pycache__"]
			rel_root = os.path.relpath(root, skill_src)
			dest_root = skill_dest_dir if rel_root == "." else os.path.join(skill_dest_dir, rel_root)
			os.makedirs(dest_root, exist_ok=True)
			for name in files:
				src_file = os.path.join(root, name)
				dest_file = os.path.join(dest_root, name)
				if name.endswith(".md"):
					resolved = subst(_read_seed(src_file), variables)
					if os.path.exists(dest_file):
						with open(dest_file, encoding="utf-8") as f:
							if f.read() == resolved:
								continue
						if backup:
							shutil.copy2(dest_file, dest_file + ".bak")
					with open(dest_file, "w", encoding="utf-8") as f:
						f.write(resolved)
				else:
					if os.path.exists(dest_file):
						with open(dest_file, "rb") as a, open(src_file, "rb") as b:
							if a.read() == b.read():
								continue
						if backup:
							shutil.copy2(dest_file, dest_file + ".bak")
					shutil.copy2(src_file, dest_file)
				skill_changed += 1
		if skill_changed:
			changed += 1
			logger.info(f"✓ Pi skill '{skill_entry}' deployed → {skill_dest_dir}")
		else:
			logger.info(f"· Pi skill '{skill_entry}' sin cambios")
	return changed


def _prune_legacy(skills_dest: str) -> int:
	"""Remove pre-rename snake_case skill dirs. Returns number removed."""
	removed = 0
	for legacy in LEGACY_SKILL_DIRS:
		path = os.path.join(skills_dest, legacy)
		if os.path.isdir(path):
			shutil.rmtree(path)
			logger.info(f"✓ Pi legacy skill '{legacy}' removed")
			removed += 1
	return removed


def _deploy_extension(pi_dir: str, seed: str, variables: dict, backup: bool) -> int:
	extensions_dir = os.path.join(pi_dir, "extensions")
	os.makedirs(extensions_dir, exist_ok=True)
	dest = os.path.join(extensions_dir, "red-pill.ts")
	resolved = subst(_read_seed(seed), variables)
	if os.path.exists(dest):
		with open(dest, encoding="utf-8") as f:
			if f.read() == resolved:
				logger.info("· Pi extension 'red-pill.ts' sin cambios")
				return 0
		if backup:
			shutil.copy2(dest, dest + ".bak")
	with open(dest, "w", encoding="utf-8") as f:
		f.write(resolved)
	logger.info(f"✓ Pi extension deployed → {dest}")
	return 1


def _remove(pi_dir: str, repo_root: str) -> int:
	removed = 0
	ext = os.path.join(pi_dir, "extensions", "red-pill.ts")
	if os.path.exists(ext):
		os.remove(ext)
		removed += 1
		logger.info("✓ Pi extension 'red-pill.ts' removed")
	skills_dest = os.path.join(pi_dir, "skills")
	managed = list(LEGACY_SKILL_DIRS)
	for src in (os.path.join(repo_root, "skills"), os.path.join(repo_root, "seeds", "pi", "skills")):
		if os.path.isdir(src):
			for entry in os.listdir(src):
				if os.path.exists(os.path.join(src, entry, "SKILL.md")):
					managed.append(entry)
	for name in sorted(set(managed)):
		path = os.path.join(skills_dest, name)
		if os.path.isdir(path):
			shutil.rmtree(path)
			removed += 1
			logger.info(f"✓ Pi skill '{name}' removed")
	return removed


def inject(args: argparse.Namespace) -> int:
	pi_dir = _pi_agent_dir()
	if not os.path.isdir(pi_dir):
		os.makedirs(pi_dir, exist_ok=True)

	script_dir = os.path.dirname(os.path.abspath(__file__))
	# scripts/inject/pi/ → scripts/ → repo root
	repo_root = os.path.normpath(os.path.join(script_dir, "..", "..", ".."))
	if not getattr(args, "redpill_dir", None):
		args.redpill_dir = repo_root  # RED_PILL_DIR / RED_PILL_CMD necesitan el checkout

	variables = build_vars(args)
	backup = not getattr(args, "no_backup", False)

	if getattr(args, "remove", False):
		return _remove(pi_dir, repo_root)

	changed = 0
	# 1. Extension
	seed_ext = os.path.join(repo_root, "seeds", "pi", "extensions", "red-pill.ts")
	if os.path.exists(seed_ext):
		changed += _deploy_extension(pi_dir, seed_ext, variables, backup)

	# 2. Skills: genérico primero, override específico-IDE después (gana).
	skills_dest = os.path.join(pi_dir, "skills")
	changed += _deploy_skills(os.path.join(repo_root, "skills"), skills_dest, variables, backup)
	changed += _deploy_skills(os.path.join(repo_root, "seeds", "pi", "skills"), skills_dest, variables, backup)
	# 3. Prune legados snake_case → reseed convergente e idempotente.
	changed += _prune_legacy(skills_dest)

	return changed
