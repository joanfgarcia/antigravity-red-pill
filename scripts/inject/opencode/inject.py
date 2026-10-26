"""Inject red-pill configuration into OpenCode.

Handles: MCP server, permissions, references, instructions (RED_PILL.md),
and skills in a single pass.  Guest principle: merge, never overwrite.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import shutil
import sys

logger = logging.getLogger("inject_opencode")

# Shared helpers — single source of truth lives at scripts/_config_common.py.
sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "..")))
from _config_common import LEGACY_SKILL_DIRS, PLUGIN_PIN, agent_core_vars, build_vars, merge_permissions, strip_jsonc_comments, subst  # noqa: E402
from migrate_opencode_v2 import migrate_file  # noqa: E402
from opencode_version import detect_info, needs_v1_plugin_pin, select_config_seed  # noqa: E402


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
			if key in ("command", "args"):
				# Comandos MCP: la lista del seed REEMPLAZA, no se concatena. Un
				# union dejaba el comando directo + el proxy mezclados.
				base[key] = val
				continue
			if key == "permissions":
				# V2 last-match-wins: no concatenar (dejaría el catch-all al final
				# pisando las reglas específicas). Insertar solo las que faltan.
				base[key] = merge_permissions(base[key], val)
				continue
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
				existing = json.loads(strip_jsonc_comments(f.read()))
		except Exception as exc:
			logger.warning(f"Unreadable config at {config_path}: {exc}. Recreating.")
			existing = {}
	merged = _deep_merge(copy.deepcopy(existing), template)
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


def _write_instructions(instructions_path: str, seeds_dir: str, variables: dict, backup: bool, update: bool) -> int:
	sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "..")))
	# Versiones de bloque: fuente única en inject_anchor.BLOCK_VERSION (este es el
	# camino de `inject_cli.py`, o sea de install y `red-pill bunker update`).
	from inject_anchor import BLOCK_ANCHORS, BLOCK_VERSION, ide_call_vars, ide_seed_path, splice_block  # noqa: E402

	# opencode tiene editor hook → el anchor debe pedir "passing only `user_prompt`".
	# Sin esto los `${RELAY_*}` del seed llegaban literales a RED_PILL.md.
	ide_vars = {**variables, **ide_call_vars("opencode")}

	changed = 0
	for anchor in BLOCK_ANCHORS:
		# Override per-IDE (seeds/opencode/anchors/<anchor>.md) si existe; si no, genérico.
		seed_path = ide_seed_path(seeds_dir, "opencode", anchor)
		if not os.path.exists(seed_path):
			logger.warning(f"Seed not found: {seed_path}")
			continue
		body = subst(_read_seed(seed_path), ide_vars)
		status = splice_block(instructions_path, anchor, body, BLOCK_VERSION[anchor], backup=backup, update=update)
		if status not in ("unchanged",):
			changed += 1
		logger.info(f"  opencode:{anchor} → {status}")
	return changed


def _skill_capability(skill_md: str) -> str | None:
	"""Lee `capability:` del frontmatter YAML de un SKILL.md (sin dependencias)."""
	try:
		with open(skill_md, encoding="utf-8") as f:
			lines = f.read().splitlines()
	except OSError:
		return None
	if not lines or lines[0].strip() != "---":
		return None
	for line in lines[1:]:
		if line.strip() == "---":
			break
		if line.startswith("capability:"):
			return line.split(":", 1)[1].strip() or None
	return None


def _deploy_skills(src_dir: str, dest_dir: str, variables: dict, backup: bool) -> int:
	"""Deploy skills with full-directory copy (SKILL.md + scripts/references).

	Multi-file skills (forge scripts, context-distiller ledger) must ship complete;
	copying only SKILL.md silently drops companions. Placeholders are resolved in
	.md files only; the rest copy byte-identical.
	"""
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
		# Gate por capacidad (docs/TECHNICAL/DECISION_LOG.md): sembrar solo si la capability está
		# activa en ESTA máquina (harness configurado). Fail-closed si no se puede verificar.
		_cap = _skill_capability(skill_md)
		if _cap is not None:
			try:
				from red_pill.core.capabilities import enabled_for

				_keep = enabled_for(_cap)
			except Exception as e:  # noqa: BLE001
				logger.warning(f"  Skill '{entry}': gate de capacidades no disponible ({e}) → skip (capability='{_cap}')")
				_keep = False
			if not _keep:
				logger.info(f"  Skill '{entry}' gated (capability '{_cap}' inactiva) → skip")
				continue
		skill_dest = os.path.join(dest_dir, entry)
		os.makedirs(skill_dest, exist_ok=True)
		skill_changed = 0
		for root, dirs, files in os.walk(skill_src):
			dirs[:] = [d for d in dirs if d != "__pycache__"]
			rel_root = os.path.relpath(root, skill_src)
			dest_root = skill_dest if rel_root == "." else os.path.join(skill_dest, rel_root)
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
			deployed += 1
			logger.info(f"  Skill '{entry}' → {skill_dest}")
	return deployed


def _deploy_agents(src_dir: str, dest_dir: str, variables: dict, backup: bool) -> int:
	"""Deploy opencode subagent definitions (seeds/opencode/agents/*.md).

	Dest: ``<config>/agents/<name>.md`` (V2 discovers ``agents/``). Placeholders
	are resolved because agents are Markdown.
	"""
	if not os.path.isdir(src_dir):
		return 0
	os.makedirs(dest_dir, exist_ok=True)
	deployed = 0
	for entry in sorted(os.listdir(src_dir)):
		if not entry.endswith(".md"):
			continue
		src = os.path.join(src_dir, entry)
		dest = os.path.join(dest_dir, entry)
		resolved = subst(_read_seed(src), variables)
		if os.path.exists(dest):
			with open(dest, encoding="utf-8") as f:
				if f.read() == resolved:
					continue
			if backup:
				shutil.copy2(dest, dest + ".bak")
		with open(dest, "w", encoding="utf-8") as f:
			f.write(resolved)
		deployed += 1
		logger.info(f"  Agent '{entry}' → {dest_dir}")
	return deployed


def _ensure_esm_package(config_dir: str, backup: bool, major: int | None) -> bool:
	"""V2: mark the plugins dir as ESM (``type: module``) to avoid Node reparsing."""
	pkg_path = os.path.join(config_dir, "package.json")
	pkg: dict = {}
	if os.path.exists(pkg_path):
		try:
			with open(pkg_path, encoding="utf-8") as f:
				pkg = json.load(f)
		except (OSError, json.JSONDecodeError):
			logger.warning(f"  {pkg_path}: unreadable JSON, not touching it")
			return False
		if not isinstance(pkg, dict):
			return False
	deps = pkg.get("dependencies")
	changed = pkg.get("type") != "module"
	if isinstance(deps, dict) and "@opencode-ai/plugin" in deps:
		deps.pop("@opencode-ai/plugin", None)
		changed = True
		if not deps:
			pkg.pop("dependencies", None)
	if not changed:
		return False
	if backup and os.path.exists(pkg_path):
		shutil.copy2(pkg_path, pkg_path + ".bak")
	pkg["type"] = "module"
	with open(pkg_path, "w", encoding="utf-8") as f:
		json.dump(pkg, f, indent=2)
		f.write("\n")
	logger.info(f"  {pkg_path}: type=module (V2 plugin ESM)")
	return True


def _ensure_package_json(config_dir: str, backup: bool, major: int | None = None) -> bool:
	"""Create package.json or refresh the @opencode-ai/plugin pin (merge, keep foreign deps).

	V1 plugins import ``@opencode-ai/plugin``; V2 plugins are plain modules and do
	not need it. On V2 we instead mark the package as ESM so Node loads the
	plugin without reparsing it as CommonJS.
	"""
	if not needs_v1_plugin_pin(major):
		return _ensure_esm_package(config_dir, backup, major)
	pkg_path = os.path.join(config_dir, "package.json")
	pkg: dict = {}
	if os.path.exists(pkg_path):
		try:
			with open(pkg_path, encoding="utf-8") as f:
				pkg = json.load(f)
		except (OSError, json.JSONDecodeError):
			logger.warning(f"  {pkg_path}: unreadable JSON, not touching it")
			return False
		if not isinstance(pkg, dict):
			logger.warning(f"  {pkg_path}: unexpected shape, not touching it")
			return False
	deps = pkg.setdefault("dependencies", {})
	if deps.get("@opencode-ai/plugin") == PLUGIN_PIN:
		return False
	if backup and os.path.exists(pkg_path):
		shutil.copy2(pkg_path, pkg_path + ".bak")
	deps["@opencode-ai/plugin"] = PLUGIN_PIN
	with open(pkg_path, "w", encoding="utf-8") as f:
		json.dump(pkg, f, indent=2)
		f.write("\n")
	logger.info(f"  {pkg_path}: @opencode-ai/plugin → {PLUGIN_PIN}")
	return True


def inject(args: argparse.Namespace) -> int:
	"""Main entry-point called by the registry dispatcher."""
	config_dir = _detect_config_dir()
	if not config_dir:
		logger.warning("OpenCode not installed (~/.config/opencode/ not found). Skipping.")
		return 0

	script_dir = os.path.dirname(os.path.abspath(__file__))
	# scripts/inject/opencode/ → scripts/ → repo root
	repo_root = os.path.normpath(os.path.join(script_dir, "..", "..", ".."))
	if not getattr(args, "redpill_dir", None):
		args.redpill_dir = repo_root  # RED_PILL_CMD necesita el checkout red-pill

	variables = build_vars(args)
	variables.update(agent_core_vars())
	backup = not getattr(args, "no_backup", False)

	opencode_seeds = os.path.join(repo_root, "seeds", "opencode")
	anchor_seeds = os.path.join(repo_root, "seeds", "anchors")
	changed = 0

	# 0. Detect the installed OpenCode version and pick the matching seed.
	config_path = os.path.join(config_dir, "opencode.jsonc")
	info = detect_info(config_path=config_path)
	if info.installed and (info.major or 0) < 2:
		raise RuntimeError(
			f"OpenCode {info} detectado. Red Pill ya NO soporta OpenCode v1. "
			"Actualiza a v2: curl -fsSL https://opencode.ai/v2/install | bash"
		)
	major = info.major
	logger.info(f"  OpenCode detectado: {info} → seed {info.tier}")

	# 1. Config (versioned seed; migrate a V1 file before merging a V2 seed).
	config_template = select_config_seed(opencode_seeds, major)
	if config_template:
		if (major or 1) >= 2 and os.path.exists(config_path):
			migrated, _, warnings = migrate_file(config_path, backup=backup)
			if migrated:
				logger.info("  opencode.jsonc: V1→V2 migrado antes de sembrar")
				for warning in warnings:
					logger.warning(f"    {warning}")
		with open(config_template, encoding="utf-8") as f:
			resolved = subst(f.read(), variables)
		_merge_config(config_path, json.loads(resolved), backup)
	else:
		logger.warning("  No config seed found for OpenCode %s", info.tier)

	# 2. Instructions
	instructions_path = os.path.join(config_dir, "RED_PILL.md")
	seeds_dir = anchor_seeds if os.path.isdir(anchor_seeds) else os.path.join(opencode_seeds, "instructions")
	changed += _write_instructions(instructions_path, seeds_dir, variables, backup, getattr(args, "update", False))

	# 3. Skills (two-layer: generic from sharing/skills/, then IDE-specific overrides)
	generic_skills = os.path.join(repo_root, "skills")
	ide_skills = os.path.join(opencode_seeds, "skills")
	skills_dest = os.path.join(config_dir, "skills")
	changed += _deploy_skills(generic_skills, skills_dest, variables, backup)
	changed += _deploy_skills(ide_skills, skills_dest, variables, backup)
	# Prune legacy snake_case dirs (renames 2026-09-10): reseed convergente e idempotente.
	for legacy in LEGACY_SKILL_DIRS:
		legacy_path = os.path.join(skills_dest, legacy)
		if os.path.isdir(legacy_path):
			shutil.rmtree(legacy_path)
			logger.info(f"✓ Skill legacy '{legacy}' removed from {skills_dest}")
			changed += 1

	# 3.5 Agents (forge-* subagents; V2 discovers <config>/agents/)
	agents_src = os.path.join(opencode_seeds, "agents")
	agents_dest = os.path.join(config_dir, "agents")
	changed += _deploy_agents(agents_src, agents_dest, variables, backup)

	# 4. Package.json
	_ensure_package_json(config_dir, backup, major)

	# 5. Plugins (redpill-scribe.js for scribe relay via hooks)
	plugins_seed = os.path.join(opencode_seeds, "plugins")
	plugins_dest = os.path.join(config_dir, "plugins")
	if os.path.isdir(plugins_seed):
		os.makedirs(plugins_dest, exist_ok=True)
		for fname in os.listdir(plugins_seed):
			src = os.path.join(plugins_seed, fname)
			dst = os.path.join(plugins_dest, fname)
			if os.path.isfile(src):
				resolved = subst(_read_seed(src), variables)
				if os.path.exists(dst):
					with open(dst, encoding="utf-8") as fdst:
						if fdst.read() == resolved:
							continue
				if backup and os.path.exists(dst):
					shutil.copy2(dst, dst + ".bak")
				with open(dst, "w", encoding="utf-8") as fdst:
					fdst.write(resolved)
				logger.info(f"  Plugin '{fname}' → {plugins_dest}")

	return changed
