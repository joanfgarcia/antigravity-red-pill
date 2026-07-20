"""Inject red-pill configuration into OpenCode.

Handles: MCP server, permissions, references, instructions (RED_PILL.md),
and skills in a single pass.  Guest principle: merge, never overwrite.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys

logger = logging.getLogger("inject_opencode")

# Shared helpers
sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "shared")))
from _config_common import agent_core_vars, build_vars, subst  # noqa: E402


def _detect_config_dir() -> str | None:
	for candidate in ["~/.config/opencode"]:
		expanded = os.path.expanduser(candidate)
		if os.path.isdir(expanded):
			return expanded
	return None


def _deep_merge(base: dict, overlay: dict) -> dict:
	for key, val in overlay.items():
		if key in base and isinstance(base[key], dict) and isinstance(val, dict):
			_deep_merge(base[key], val)
		elif key in base and isinstance(base[key], list) and isinstance(val, list):
			for item in val:
				if item not in base[key]:
					base[key].append(item)
		else:
			base[key] = val
	return base


def _read_seed(path: str) -> str:
	with open(path, encoding="utf-8") as f:
		return f.read()


def _merge_config(config_path: str, template: dict, backup: bool) -> bool:
	existing = {}
	if os.path.exists(config_path):
		try:
			with open(config_path, encoding="utf-8") as f:
				content = f.read()
				content = re.sub(r"//.*$", "", content, flags=re.MULTILINE)
				content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
				existing = json.loads(content)
		except Exception as exc:
			logger.warning(f"Unreadable config at {config_path}: {exc}. Recreating.")
			existing = {}
	merged = _deep_merge(existing, template)
	if merged == existing and existing:
		logger.info(f"  {config_path}: sin cambios")
		return False
	if backup and os.path.exists(config_path):
		shutil.copy2(config_path, config_path + ".bak")
	os.makedirs(os.path.dirname(config_path), exist_ok=True)
	with open(config_path, "w", encoding="utf-8") as f:
		json.dump(merged, f, indent=2, ensure_ascii=False)
		f.write("\n")
	logger.info(f"  {config_path}: actualizado")
	return True


def _write_instructions(instructions_path: str, seeds_dir: str, variables: dict,
						backup: bool, update: bool) -> int:
	sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "..")))
	from inject_anchor import splice_block  # noqa: E402

	BLOCK_VERSION = {"sovereign_handshake": 1, "agent_core": 2, "knowledge_access": 2}
	changed = 0
	for anchor in ["sovereign_handshake", "agent_core", "knowledge_access"]:
		seed_path = os.path.join(seeds_dir, anchor + ".md")
		if not os.path.exists(seed_path):
			logger.warning(f"Seed not found: {seed_path}")
			continue
		body = subst(_read_seed(seed_path), variables)
		status = splice_block(instructions_path, anchor, body,
							  BLOCK_VERSION[anchor], backup=backup, update=update)
		if status not in ("unchanged",):
			changed += 1
		logger.info(f"  opencode:{anchor} → {status}")
	return changed


def _deploy_skills(src_dir: str, dest_dir: str, variables: dict, backup: bool) -> int:
	deployed = 0
	if not os.path.isdir(src_dir):
		return 0
	for entry in os.listdir(src_dir):
		skill_src = os.path.join(src_dir, entry)
		if not os.path.isdir(skill_src):
			continue
		skill_md = os.path.join(skill_src, "SKILL.md")
		if not os.path.exists(skill_md):
			continue
		dest = os.path.join(dest_dir, entry, "SKILL.md")
		os.makedirs(os.path.dirname(dest), exist_ok=True)
		resolved = subst(_read_seed(skill_md), variables)
		if os.path.exists(dest):
			with open(dest, encoding="utf-8") as f:
				if f.read() == resolved:
					continue
			if backup:
				shutil.copy2(dest, dest + ".bak")
		with open(dest, "w", encoding="utf-8") as f:
			f.write(resolved)
		deployed += 1
		logger.info(f"  Skill '{entry}' → {os.path.dirname(dest)}")
	return deployed


def _ensure_package_json(config_dir: str, backup: bool) -> bool:
	pkg_path = os.path.join(config_dir, "package.json")
	if os.path.exists(pkg_path):
		return False
	pkg = {"dependencies": {"@opencode-ai/plugin": "1.18.3"}}
	with open(pkg_path, "w", encoding="utf-8") as f:
		json.dump(pkg, f, indent=2)
		f.write("\n")
	logger.info(f"  {pkg_path}: created")
	return True


def inject(args: argparse.Namespace) -> int:
	"""Main entry-point called by the registry dispatcher."""
	config_dir = _detect_config_dir()
	if not config_dir:
		logger.warning("OpenCode not installed (~/.config/opencode/ not found). Skipping.")
		return 0

	variables = build_vars(args)
	variables.update(agent_core_vars())
	backup = not getattr(args, "no_backup", False)

	script_dir = os.path.dirname(os.path.abspath(__file__))
	repo_root = os.path.join(script_dir, "..", "..")
	opencode_seeds = os.path.join(repo_root, "seeds", "opencode")
	anchor_seeds = os.path.join(repo_root, "seeds", "anchors")
	changed = 0

	# 1. Config
	config_template = os.path.join(opencode_seeds, "settings", "opencode.jsonc")
	if os.path.exists(config_template):
		with open(config_template, encoding="utf-8") as f:
			resolved = subst(f.read(), variables)
		_merge_config(os.path.join(config_dir, "opencode.jsonc"), json.loads(resolved), backup)

	# 2. Instructions
	instructions_path = os.path.join(config_dir, "RED_PILL.md")
	seeds_dir = anchor_seeds if os.path.isdir(anchor_seeds) else os.path.join(opencode_seeds, "instructions")
	changed += _write_instructions(instructions_path, seeds_dir, variables,
								   backup, getattr(args, "update", False))

	# 3. Skills (two-layer: generic from sharing/skills/, then IDE-specific overrides)
	generic_skills = os.path.join(repo_root, "skills")
	ide_skills = os.path.join(opencode_seeds, "skills")
	skills_dest = os.path.join(config_dir, "skills")
	changed += _deploy_skills(generic_skills, skills_dest, variables, backup)
	changed += _deploy_skills(ide_skills, skills_dest, variables, backup)

	# 4. Package.json
	_ensure_package_json(config_dir, backup)

	# 5. Plugins (redpill-scribe.js for scribe relay via hooks)
	plugins_seed = os.path.join(opencode_seeds, "plugins")
	plugins_dest = os.path.join(config_dir, "plugins")
	if os.path.isdir(plugins_seed):
		os.makedirs(plugins_dest, exist_ok=True)
		for fname in os.listdir(plugins_seed):
			src = os.path.join(plugins_seed, fname)
			dst = os.path.join(plugins_dest, fname)
			if os.path.isfile(src):
				if os.path.exists(dst):
					with open(src, encoding="utf-8") as fsrc, open(dst, encoding="utf-8") as fdst:
						if fsrc.read() == fdst.read():
							continue
					if backup:
						shutil.copy2(dst, dst + ".bak")
				shutil.copy2(src, dst)
				logger.info(f"  Plugin '{fname}' → {plugins_dest}")

	return changed
