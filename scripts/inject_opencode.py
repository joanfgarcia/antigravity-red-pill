"""Inject red-pill configuration into opencode.

Sibling of ``inject_mcp.py`` / ``inject_anchor.py``. Handles the three layers
opencode consolidates into a single ``opencode.jsonc``: MCP server entry,
permissions (external_directory), and references. Also deploys the RED_PILL.md
instructions file and opencode-specific skills.

Guiding principle: red-pill is a GUEST, never the owner. Every write preserves
all foreign content; we only ever create/replace/remove OUR own marked regions
or keys.

Seeds live in ``seeds/opencode/`` and are passed through the shared ``subst()``
so placeholders like ${HOME}/${REDPILL_DIR}/${AGENT_CORE_DIR} resolve.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("opencode_injector")

# Shared placeholder helpers live alongside this script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config_common import agent_core_vars, build_vars, strip_jsonc_comments, subst  # noqa: E402

# ── Config directory discovery ────────────────────────────────────────────────
OPENCODE_CONFIG_DIRS = [
	"~/.config/opencode",
]


def detect_config_dir() -> str | None:
	"""Return the opencode config directory if it exists."""
	for candidate in OPENCODE_CONFIG_DIRS:
		expanded = os.path.expanduser(candidate)
		if os.path.isdir(expanded):
			return expanded
	return None


# ── opencode.jsonc merge ──────────────────────────────────────────────────────
def _deep_merge(base: dict, overlay: dict) -> dict:
	"""Recursively merge *overlay* into *base*. Lists are unioned (dedupe),
	dicts recursed, scalars overwritten. Returns *base* mutated."""
	for key, val in overlay.items():
		if key in base and isinstance(base[key], dict) and isinstance(val, dict):
			_deep_merge(base[key], val)
		elif key in base and isinstance(base[key], list) and isinstance(val, list):
			existing = base[key]
			for item in val:
				if item not in existing:
					existing.append(item)
		else:
			base[key] = val
	return base


def merge_opencode_config(config_path: str, template: dict, backup: bool = True) -> bool:
	"""Merge red-pill keys into existing opencode.jsonc. Preserves all foreign keys."""
	existing = {}
	if os.path.exists(config_path):
		try:
			with open(config_path, encoding="utf-8") as f:
				existing = json.loads(strip_jsonc_comments(f.read()))
		except Exception as exc:
			logger.warning(f"Unreadable config at {config_path}: {exc}. Recreating.")
			existing = {}

	# Snapshot before merge to detect actual changes (deep_merge mutates base)
	existing_snapshot = json.loads(json.dumps(existing))
	merged = _deep_merge(existing, template)

	if merged == existing_snapshot and existing_snapshot:
		logger.info(f"• {config_path}: sin cambios (ya presente)")
		return False

	if backup and os.path.exists(config_path):
		shutil.copy2(config_path, config_path + ".bak")

	os.makedirs(os.path.dirname(config_path), exist_ok=True)
	with open(config_path, "w", encoding="utf-8") as f:
		json.dump(merged, f, indent=2, ensure_ascii=False)
		f.write("\n")
	logger.info(f"✓ {config_path}: configuración opencode actualizada")
	return True


# ── Instructions file (RED_PILL.md) ──────────────────────────────────────────
# Reuse the anchor splice logic from inject_anchor.py for versioned blocks.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inject_anchor import remove_block, splice_block  # noqa: E402

BLOCK_VERSION = {"sovereign_handshake": 1, "agent_core": 2, "knowledge_access": 2}


def _read_seed(seed_path: str) -> str:
	with open(seed_path, encoding="utf-8") as f:
		return f.read()


def write_instructions(instructions_path: str, seeds_dir: str, variables: dict, backup: bool = True, update: bool = False) -> int:
	"""Write RED_PILL.md with versioned anchor blocks. Returns count of changed blocks."""
	anchor_names = ["sovereign_handshake", "agent_core", "knowledge_access"]
	changed = 0

	for anchor in anchor_names:
		seed_path = os.path.join(seeds_dir, anchor + ".md")
		if not os.path.exists(seed_path):
			# Fallback: try the consolidated RED_PILL.md seed
			seed_path = os.path.join(seeds_dir, "..", "instructions", "RED_PILL.md")
			if os.path.exists(seed_path):
				# For consolidated seed, extract the individual block
				raw = _read_seed(seed_path)
				# Extract block between markers
				pattern = re.compile(
					r"<!-- REDPILL:BEGIN %s(?: v=\d+)? -->.*?<!-- REDPILL:END %s -->" % (re.escape(anchor), re.escape(anchor)),
					re.DOTALL,
				)
				m = pattern.search(raw)
				if m:
					# Extract just the body (between markers)
					block_text = m.group(0)
					body_start = block_text.find("\n") + 1
					body_end = block_text.rfind("\n")
					body = block_text[body_start:body_end].strip()
					status = splice_block(instructions_path, anchor, body, BLOCK_VERSION[anchor], backup=backup, update=update)
					if status not in ("unchanged",):
						changed += 1
					logger.info(f"✓ opencode:{anchor} [{instructions_path}] → {status}")
				continue
			logger.warning(f"Seed not found for anchor '{anchor}': {seed_path}")
			continue

		raw = _read_seed(seed_path)
		body = subst(raw, variables)
		status = splice_block(instructions_path, anchor, body, BLOCK_VERSION[anchor], backup=backup, update=update)
		if status not in ("unchanged",):
			changed += 1
		logger.info(f"✓ opencode:{anchor} [{instructions_path}] → {status}")

	return changed


# ── Skills deployment ─────────────────────────────────────────────────────────
def deploy_skills(skills_src_dir: str, skills_dest_dir: str, variables: dict, backup: bool = True) -> int:
	"""Deploy opencode skills with resolved placeholders. Returns count deployed.

	Full-directory copy (SKILL.md + references/ + scripts/ + schemas/), so
	multi-file skills like forge ship complete. Placeholder resolution
	applies ONLY to .md files; scripts/binaries copy byte-identical.
	"""
	deployed = 0
	if not os.path.isdir(skills_src_dir):
		logger.warning(f"Skills source dir not found: {skills_src_dir}")
		return 0

	for skill_entry in os.listdir(skills_src_dir):
		skill_src = os.path.join(skills_src_dir, skill_entry)
		skill_md = os.path.join(skill_src, "SKILL.md")
		if not os.path.isdir(skill_src) or not os.path.exists(skill_md):
			continue

		skill_dest_dir = os.path.join(skills_dest_dir, skill_entry)
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
					if os.path.exists(dest_file) and _same_file(src_file, dest_file):
						continue
					if backup and os.path.exists(dest_file):
						shutil.copy2(dest_file, dest_file + ".bak")
					shutil.copy2(src_file, dest_file)
				skill_changed += 1

		if skill_changed:
			deployed += 1
			logger.info(f"✓ Skill '{skill_entry}' desplegada (copia completa) en {skill_dest_dir}")
		else:
			logger.info(f"· Skill '{skill_entry}' sin cambios")

	return deployed


def _same_file(a: str, b: str) -> bool:
	import hashlib

	def digest(p: str) -> str:
		h = hashlib.sha256()
		with open(p, "rb") as f:
			for chunk in iter(lambda: f.read(65536), b""):
				h.update(chunk)
		return h.hexdigest()

	return os.path.exists(a) and os.path.exists(b) and digest(a) == digest(b)


# ── Agents deployment ─────────────────────────────────────────────────────────
def deploy_agents(agents_src_dir: str, agents_dest_dir: str, variables: dict, backup: bool = True) -> int:
	"""Deploy opencode subagent definitions (seeds/opencode/agents/forge-*.md).

	Dest: <config>/agents/<name>.md (opencode loads agents from
	~/.config/opencode/agents/). Placeholders resolved (agents are markdown).
	"""
	deployed = 0
	if not os.path.isdir(agents_src_dir):
		logger.warning(f"Agents source dir not found: {agents_src_dir}")
		return 0

	os.makedirs(agents_dest_dir, exist_ok=True)
	for entry in sorted(os.listdir(agents_src_dir)):
		if not entry.endswith(".md"):
			continue
		src = os.path.join(agents_src_dir, entry)
		dest = os.path.join(agents_dest_dir, entry)
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
		logger.info(f"✓ Agent '{entry}' desplegado en {agents_dest_dir}")

	return deployed


# ── Version drift check (semver in frontmatter) ───────────────────────────────
_VERSION_RE = re.compile(r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)", re.MULTILINE)


def _frontmatter_version(path: str) -> str | None:
	"""Return the `version:` value from the frontmatter of a seed/deployed file."""
	try:
		with open(path, encoding="utf-8") as f:
			head = f.read(2048)
	except OSError:
		return None
	m = _VERSION_RE.search(head)
	return m.group(1) if m else None


def check_version_drift(seeds_dir: str, deployed_dir: str, kind: str = "skills") -> int:
	"""Report version mismatches between seed and deployed skills/agents.

	Read-only audit: compares `version:` in frontmatter of every seed skill
	(seeds/opencode/skills/*/SKILL.md) or agent (seeds/opencode/agents/*.md)
	against the deployed copy. Returns the number of drifts found. A drift means
	one side was edited and the other not re-synced — the gate-check of the
	deploy.
	"""
	drifts = 0
	if not os.path.isdir(seeds_dir) or not os.path.isdir(deployed_dir):
		return 0
	if kind == "agents":
		# Agents: <seed>/<name>.md vs <deployed>/<name>.md
		for name in sorted(os.listdir(seeds_dir)):
			seed_file = os.path.join(seeds_dir, name)
			deployed_file = os.path.join(deployed_dir, name)
			if not os.path.isfile(seed_file) or not name.endswith(".md"):
				continue
			sv, dv = _frontmatter_version(seed_file), _frontmatter_version(deployed_file)
			if dv != sv:
				drifts += 1
				logger.warning(f"⚠ Agent '{name}': seed v{sv or '?'} vs deployed v{dv or '?'} — re-run inject or sync seeds")
	else:
		# Skills: <seed>/<name>/SKILL.md vs <deployed>/<name>/SKILL.md
		for name in sorted(os.listdir(seeds_dir)):
			seed_file = os.path.join(seeds_dir, name, "SKILL.md")
			deployed_file = os.path.join(deployed_dir, name, "SKILL.md")
			if not os.path.isfile(seed_file):
				continue
			sv, dv = _frontmatter_version(seed_file), _frontmatter_version(deployed_file)
			if dv != sv:
				drifts += 1
				logger.warning(f"⚠ Skill '{name}': seed v{sv or '?'} vs deployed v{dv or '?'} — re-run inject or sync seeds")
	if drifts == 0:
		logger.info(f"✓ Version drift check: all seeds and deployed {kind} in sync")
	return drifts


# ── package.json bootstrap ────────────────────────────────────────────────────
def deploy_plugins(plugins_src_dir: str, plugins_dest_dir: str, variables: dict, backup: bool = True) -> int:
	"""Deploy opencode plugins with resolved placeholders. Returns count deployed.

	The scribe plugin is the capture surface for every opencode turn, so a seed
	that never reaches the host is a month of lost memory. This step existed only
	in the (uncalled) adapter under scripts/inject/opencode/, which is why edits
	to the seed silently stayed in the repo.
	"""
	deployed = 0
	if not os.path.isdir(plugins_src_dir):
		return deployed

	os.makedirs(plugins_dest_dir, exist_ok=True)
	for fname in os.listdir(plugins_src_dir):
		src = os.path.join(plugins_src_dir, fname)
		if not os.path.isfile(src):
			continue
		dst = os.path.join(plugins_dest_dir, fname)
		resolved = subst(_read_seed(src), variables)
		if os.path.exists(dst):
			with open(dst, encoding="utf-8") as fdst:
				if fdst.read() == resolved:
					continue
			if backup:
				shutil.copy2(dst, dst + ".bak")
		with open(dst, "w", encoding="utf-8") as fdst:
			fdst.write(resolved)
		logger.info(f"✓ Plugin '{fname}' desplegado en {plugins_dest_dir}")
		deployed += 1
	return deployed


def ensure_package_json(config_dir: str, backup: bool = True) -> bool:
	"""Create package.json with @opencode-ai/plugin if it doesn't exist."""
	pkg_path = os.path.join(config_dir, "package.json")
	if os.path.exists(pkg_path):
		return False
	pkg = {"dependencies": {"@opencode-ai/plugin": "1.18.3"}}
	if backup and os.path.exists(pkg_path):
		shutil.copy2(pkg_path, pkg_path + ".bak")
	with open(pkg_path, "w", encoding="utf-8") as f:
		json.dump(pkg, f, indent=2)
		f.write("\n")
	logger.info(f"✓ {pkg_path}: created with @opencode-ai/plugin dependency")
	return True


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
	parser = argparse.ArgumentParser(description="Inject red-pill configuration into opencode (MCP, permissions, references, instructions, skills).")
	parser.add_argument("--uv-path", help="Path to uv. Autodetected if omitted.")
	parser.add_argument("--redpill-dir", help="Path to Red Pill source directory.")
	parser.add_argument("--update", action="store_true", help="Force-update anchor blocks even if unchanged.")
	parser.add_argument("--no-backup", action="store_true", help="Do not write .bak files before modifying.")
	parser.add_argument("--print", dest="print_only", action="store_true", help="Print resolved config to stdout; touch no files.")
	parser.add_argument("--remove", action="store_true", help="Remove red-pill config from opencode.")
	args = parser.parse_args()

	# Detect opencode
	config_dir = detect_config_dir()
	if not config_dir:
		logger.error("opencode config directory not found (~/.config/opencode/). Install opencode first or create the directory.")
		sys.exit(1)

	# Resolve variables
	variables = build_vars(args)
	variables.update(agent_core_vars())

	# Seed paths
	script_dir = os.path.dirname(os.path.abspath(__file__))
	repo_root = os.path.join(script_dir, "..")
	opencode_seeds = os.path.join(repo_root, "seeds", "opencode")

	backup = not args.no_backup

	# ── Remove mode ────────────────────────────────────────────────────────
	if args.remove:
		# Remove RED_PILL.md anchor blocks
		instructions_path = os.path.join(config_dir, "RED_PILL.md")
		if os.path.exists(instructions_path):
			for anchor in ["sovereign_handshake", "agent_core", "knowledge_access"]:
				status = remove_block(instructions_path, anchor, backup=backup)
				if status != "absent":
					logger.info(f"✓ opencode:{anchor} removed [{instructions_path}]")
		# Remove skills — derived from the seeds dir (whatever deploy_skills
		# ships), not a hardcoded list that rots when a new skill is seeded.
		skills_dir = os.path.join(config_dir, "skills")
		seeded_skills = set()
		skills_src = os.path.join(opencode_seeds, "skills")
		if os.path.isdir(skills_src):
			for entry in os.listdir(skills_src):
				if os.path.exists(os.path.join(skills_src, entry, "SKILL.md")):
					seeded_skills.add(entry)
		seeded_skills.update(["sovereign_handshake", "agent_core", "knowledge_access"])  # legacy anchor-skills
		for skill_name in sorted(seeded_skills):
			skill_path = os.path.join(skills_dir, skill_name)
			if os.path.isdir(skill_path):
				shutil.rmtree(skill_path)
				logger.info(f"✓ Skill '{skill_name}' removed")
		# Remove agents (forge-*)
		agents_dir = os.path.join(config_dir, "agents")
		for entry in os.listdir(agents_dir) if os.path.isdir(agents_dir) else []:
			if entry.startswith("forge-") and entry.endswith(".md"):
				os.remove(os.path.join(agents_dir, entry))
				logger.info(f"✓ Agent '{entry}' removed")
		logger.info("Red Pill removed from opencode.")
		return

	# ── Print mode ─────────────────────────────────────────────────────────
	if args.print_only:
		config_template = os.path.join(opencode_seeds, "settings", "opencode.jsonc")
		if os.path.exists(config_template):
			with open(config_template, encoding="utf-8") as f:
				raw = f.read()
			# Resolve ${} placeholders but leave {env:} for opencode
			for key, val in variables.items():
				raw = raw.replace("${%s}" % key, val)
			print("===== OPENCODE CONFIG (preview) =====")
			print(raw)
		return

	# ── 1. Merge opencode.jsonc ────────────────────────────────────────────
	config_template_path = os.path.join(opencode_seeds, "settings", "opencode.jsonc")
	config_dest = os.path.join(config_dir, "opencode.jsonc")

	if os.path.exists(config_template_path):
		with open(config_template_path, encoding="utf-8") as f:
			raw_template = f.read()
		resolved = subst(raw_template, variables)
		template = json.loads(resolved)
		merge_opencode_config(config_dest, template, backup=backup)

	# ── 2. Write instructions (RED_PILL.md) ────────────────────────────────
	instructions_path = os.path.join(config_dir, "RED_PILL.md")
	instructions_seeds = os.path.join(opencode_seeds, "instructions")

	# Also check the consolidated seed and individual anchor seeds
	anchor_seeds_dir = os.path.join(repo_root, "seeds", "anchors")
	if os.path.isdir(anchor_seeds_dir):
		# Use individual anchor seeds (canonical source)
		write_instructions(instructions_path, anchor_seeds_dir, variables, backup=backup, update=args.update)
	else:
		# Fallback to consolidated instruction seed
		write_instructions(instructions_path, instructions_seeds, variables, backup=backup, update=args.update)

	# ── 3. Deploy skills ───────────────────────────────────────────────────
	skills_src = os.path.join(opencode_seeds, "skills")
	skills_dest = os.path.join(config_dir, "skills")
	deploy_skills(skills_src, skills_dest, variables, backup=backup)

	# ── 3.5 Deploy agents (swarm-* subagents) ──────────────────────────────
	agents_src = os.path.join(opencode_seeds, "agents")
	agents_dest = os.path.join(config_dir, "agents")
	deploy_agents(agents_src, agents_dest, variables, backup=backup)

	# ── 4. Ensure package.json ─────────────────────────────────────────────
	ensure_package_json(config_dir, backup=backup)

	# ── 5. Deploy plugins (the scribe that captures every turn) ────────────
	plugins_src = os.path.join(opencode_seeds, "plugins")
	plugins_dest = os.path.join(config_dir, "plugins")
	deploy_plugins(plugins_src, plugins_dest, variables, backup=backup)

	# ── 6. Version drift audit (read-only) ─────────────────────────────────
	skills_seeds_dir = os.path.join(opencode_seeds, "skills")
	agents_seeds_dir = os.path.join(opencode_seeds, "agents")
	check_version_drift(skills_seeds_dir, os.path.join(config_dir, "skills"), kind="skills")
	if os.path.isdir(agents_seeds_dir):
		check_version_drift(agents_seeds_dir, agents_dest, kind="agents")

	logger.info("OpenCode + Red Pill integration complete.")


if __name__ == "__main__":
	main()
