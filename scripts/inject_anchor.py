"""Inject/merge red-pill anchor blocks into IDE instruction files.

Sibling of ``inject_mcp.py``. Where inject_mcp merges MCP server entries into
``*.json`` configs by key, this merges Markdown anchor *blocks* (the Sovereign
Handshake, the Agent_Core directive) into IDE instruction files (GEMINI.md,
CLAUDE.md, …) by a delimited, versioned region.

Guiding principle: red-pill is a GUEST, never the owner. Every write preserves
all foreign content; we only ever create/replace/remove OUR own marked region:

<!-- REDPILL:BEGIN <anchor> v=N -->
…seed body (placeholders resolved)…
<!-- REDPILL:END <anchor> -->

Seeds live in ``seeds/anchors/<anchor>.md`` and are passed through the shared
``subst()`` so placeholders like ${WORKSPACE_ROOT}/${AGENT_CORE_DIR} resolve.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("anchor_injector")

# Shared placeholder helpers live alongside this script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config_common import agent_core_vars, build_vars, subst  # noqa: E402

# ── Anchor block version (bump to force a re-splice on upgrade) ───────────────
BLOCK_VERSION = {"sovereign_handshake": 1, "agent_core": 2}


def _version(anchor):
	return BLOCK_VERSION.get(anchor, 1)


# ── IDE → anchor-file registry (everything is merge; no "owner" files) ────────
@dataclass(frozen=True)
class AnchorTarget:
	ide: str
	path: str | None  # static path (with ~); None => resolved at runtime / not a file
	requires_workspace: bool  # path depends on --workspace
	scriptable: bool  # False => lives in app UI/DB, only --print


ANCHOR_REGISTRY = [
	AnchorTarget("antigravity", "~/.gemini/GEMINI.md", False, True),  # user-level, global
	AnchorTarget("claude-code", "~/.claude/CLAUDE.md", False, True),  # user memory: global, cwd-independent
	AnchorTarget("claude-code-project", None, True, True),  # <workspace>/CLAUDE.md (project-scoped, opt-in)
	AnchorTarget("claude-desktop-project", None, False, False),  # Project instructions: UI/DB, only --print
]
REGISTRY_BY_IDE = {t.ide: t for t in ANCHOR_REGISTRY}


def _claude_desktop_present():
	for p in (
		"~/.config/Claude/claude_desktop_config.json",
		"~/Library/Application Support/Claude/claude_desktop_config.json",
		"~/AppData/Roaming/Claude/claude_desktop_config.json",
	):
		if os.path.exists(os.path.expanduser(p)):
			return True
	return False


def detect_present_ides(workspace):
	"""IDEs to target under --ide auto. antigravity + claude-code anchors are user-level/global
	(cwd-independent). claude-desktop-project is included when Desktop is installed so we can REMIND
	the user to paste it (its Project instructions aren't scriptable). claude-code-project is opt-in
	only (never auto): it would duplicate the handshake already in user memory."""
	present = []
	if os.path.isdir(os.path.expanduser("~/.gemini")):
		present.append("antigravity")
	if os.path.isdir(os.path.expanduser("~/.claude")):
		present.append("claude-code")
	if _claude_desktop_present():
		present.append("claude-desktop-project")
	return present


def resolve_target_path(target, workspace):
	if target.ide == "claude-code-project":
		return os.path.join(os.path.expanduser(workspace), "CLAUDE.md") if workspace else None
	return os.path.expanduser(target.path) if target.path else None


def ide_call_vars(ide):
	"""Per-IDE tool-call phrasing for the handshake (${RELAY_CALL}/${WAKE_CALL}).
	Antigravity is lax — the server's compatibility shim resolves the flat action name.
	Claude clients only call the ADVERTISED consolidated APIs, so they must use the
	`<api>` tool + an `action` argument (the flat name is not a tool for them)."""
	if ide == "antigravity":
		return {
			"RELAY_CALL": "`mcp_RedPill-Kernel_interceptor_rp`",
			"WAKE_CALL": "`mcp_RedPill-Kernel_refresh_session_context`",
		}
	return {
		"RELAY_CALL": 'the `swarm_orchestrator_api` tool with `{"action": "interceptor_rp", "payload": {...}}`',
		"WAKE_CALL": 'the `bunker_memory_api` tool with `{"action": "refresh_session_context", "payload": {}}`',
	}


# ── Block construction + matching ─────────────────────────────────────────────
def _build_block(anchor, body, version):
	begin = "<!-- REDPILL:BEGIN %s v=%d -->" % (anchor, version)
	end = "<!-- REDPILL:END %s -->" % anchor
	return "%s\n%s\n%s" % (begin, body.strip(), end)


def _marker_re(anchor):
	a = re.escape(anchor)
	return re.compile(
		r"<!-- REDPILL:BEGIN %s(?: v=\d+)? -->.*?<!-- REDPILL:END %s -->" % (a, a),
		re.DOTALL,
	)


# Legacy (pre-marker) red-pill content to clean up during a one-time migration.
LEGACY_CONSTRAINT_NAMES = {
	"sovereign_handshake": "sovereign_handshake",
	"agent_core": "sovereign_atlas_awareness",
}
LEGACY_HEADING_RE = re.compile(r"^## (?:1\. Zero-Trust|2\. Model Change|3\. Persistent Memory).*\n?", re.MULTILINE)


def _legacy_constraint_re(name):
	return re.compile(
		r'<constraint\b[^>]*\bname="%s"[^>]*>.*?</constraint>[ \t]*\n?' % re.escape(name),
		re.DOTALL,
	)


def _atomic_write(path, content, backup=True):
	parent = os.path.dirname(os.path.abspath(path))
	os.makedirs(parent, exist_ok=True)
	if backup and os.path.exists(path):
		shutil.copy2(path, path + ".bak")
	tmp = path + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		f.write(content)
	os.replace(tmp, path)


def _append_block(content, new_block):
	content = content.rstrip("\n")
	return (content + "\n\n" + new_block + "\n") if content else (new_block + "\n")


def splice_block(path, anchor, body, version, backup=True, update=False):
	"""Merge OUR marked region into `path`, preserving everything else.
	Returns one of: created | updated | unchanged | migrated."""
	new_block = _build_block(anchor, body, version)
	path = os.path.expanduser(path)

	if not os.path.exists(path):
		_atomic_write(path, new_block + "\n", backup=False)
		return "created"

	with open(path, encoding="utf-8") as f:
		content = f.read()

	mre = _marker_re(anchor)
	if mre.search(content):
		# Replace the first marked region; drop any accidental duplicates.
		state = {"n": 0}

		def _repl(_m):
			state["n"] += 1
			return new_block if state["n"] == 1 else ""

		new_content, _ = mre.subn(_repl, content)
		if new_content == content and not update:
			return "unchanged"
		_atomic_write(path, new_content, backup=backup)
		return "updated"

	# No marked region yet → migrate legacy red-pill content, else append.
	migrated = content
	if anchor == "sovereign_handshake":
		migrated = LEGACY_HEADING_RE.sub("", migrated)

	legacy_name = LEGACY_CONSTRAINT_NAMES.get(anchor)
	replaced = False
	if legacy_name:
		state = {"n": 0}

		def _repl_legacy(_m):
			# Replacement text is NOT re-scanned, so the new block (which may
			# contain the same constraint name) is safe from this regex.
			state["n"] += 1
			return (new_block + "\n") if state["n"] == 1 else ""

		migrated, count = _legacy_constraint_re(legacy_name).subn(_repl_legacy, migrated)
		replaced = count > 0

	if replaced:
		new_content = re.sub(r"\n{3,}", "\n\n", migrated)
		_atomic_write(path, new_content, backup=backup)
		return "migrated"

	_atomic_write(path, _append_block(migrated, new_block), backup=backup)
	return "migrated" if migrated != content else "appended"


def remove_block(path, anchor, backup=True):
	"""Remove OUR marked region only. Delete the file if nothing else remains."""
	path = os.path.expanduser(path)
	if not os.path.exists(path):
		return "absent"
	with open(path, encoding="utf-8") as f:
		content = f.read()
	mre = _marker_re(anchor)
	if not mre.search(content):
		return "absent"
	new_content = re.sub(r"\n{3,}", "\n\n", mre.sub("", content)).strip()
	if not new_content:
		if backup:
			shutil.copy2(path, path + ".bak")
		os.remove(path)
		return "removed-file"
	_atomic_write(path, new_content + "\n", backup=backup)
	return "removed-block"


def _csv(value):
	return [x.strip() for x in value.split(",") if x.strip()]


def main():
	parser = argparse.ArgumentParser(description="Inject/merge red-pill anchor blocks into IDE instruction files.")
	parser.add_argument("--ide", default="auto", help="csv: auto|all|antigravity|claude-code|claude-desktop-project")
	parser.add_argument("--anchor", default="sovereign_handshake,agent_core", help="csv of anchor seeds to inject (file names in --seeds-dir)")
	parser.add_argument("--workspace", help="Workspace root: resolves ${WORKSPACE} and targets Claude Code <ws>/CLAUDE.md")
	parser.add_argument("--redpill-dir", help="Red Pill source dir (resolves ${REDPILL_DIR}).")
	parser.add_argument("--uv-path", help="Path to uv (shared build_vars; current anchors don't use it).")
	parser.add_argument("--seeds-dir", help="Dir with <anchor>.md seeds. Default: ../seeds/anchors next to this script.")
	parser.add_argument("--update", action="store_true", help="Rewrite the block even if unchanged.")
	parser.add_argument("--no-backup", action="store_true", help="Do not write a .bak before modifying.")
	parser.add_argument("--print", dest="print_only", action="store_true", help="Print resolved anchor(s) to stdout; touch no files.")
	parser.add_argument("--remove", action="store_true", help="Remove red-pill anchor block(s) instead of writing.")
	args = parser.parse_args()

	if args.seeds_dir:
		seeds_dir = os.path.abspath(os.path.expanduser(args.seeds_dir))
	else:
		seeds_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "seeds", "anchors"))

	anchors = _csv(args.anchor)
	if not anchors:
		parser.error("--anchor vacío")
	if not args.remove:
		for a in anchors:
			seed = os.path.join(seeds_dir, a + ".md")
			if not os.path.exists(seed):
				parser.error(f"seed no encontrado para anchor '{a}': {seed}")

	tokens = _csv(args.ide)
	if "auto" in tokens:
		ides = detect_present_ides(args.workspace)
	elif "all" in tokens:
		ides = [t.ide for t in ANCHOR_REGISTRY]
	else:
		ides = []
		for tok in tokens:
			if tok not in REGISTRY_BY_IDE:
				parser.error(f"IDE desconocido: {tok}")
			ides.append(tok)

	if not ides:
		logger.warning("No hay IDEs objetivo (¿falta --workspace para claude-code?). Nada que hacer.")
		return

	variables = build_vars(args)
	variables.update(agent_core_vars())

	raw_bodies = {}
	if not args.remove:
		for a in anchors:
			with open(os.path.join(seeds_dir, a + ".md"), encoding="utf-8") as f:
				raw_bodies[a] = f.read()

	backup = not args.no_backup
	changed = 0
	reminders = 0
	for ide in ides:
		target = REGISTRY_BY_IDE[ide]
		path = resolve_target_path(target, args.workspace)
		# Resolve bodies per-IDE: ${RELAY_CALL}/${WAKE_CALL} differ by client (see ide_call_vars).
		bodies = {a: subst(raw_bodies[a], {**variables, **ide_call_vars(ide)}) for a in anchors} if not args.remove else {}

		# Non-scriptable target (Claude Desktop Project instructions live in the app UI/DB).
		if not target.scriptable:
			if args.remove:
				logger.warning(f"• {ide}: --remove no aplica (no es un fichero); omitido.")
				continue
			if args.print_only:
				print(f"\n===== ANCHOR · {ide} (paste into Project instructions) =====")
				print("\n\n".join(_build_block(a, bodies[a], _version(a)) for a in anchors))
			else:
				logger.warning(
					f"• {ide}: RECORDATORIO — las instrucciones del Project de Claude Desktop NO son "
					f"scriptables (viven en la app). Pégalas a mano en Claude Desktop → Projects → tu "
					f"proyecto → Instrucciones. Obtén el texto con:\n"
					f"    uv run python scripts/inject_anchor.py --ide {ide} --print"
				)
				reminders += 1
			continue

		# Forced preview of a scriptable target.
		if args.print_only:
			print(f"\n===== ANCHOR · {ide} (preview) =====")
			print("\n\n".join(_build_block(a, bodies[a], _version(a)) for a in anchors))
			continue

		if target.requires_workspace and not args.workspace:
			logger.warning(f"• {ide}: requiere --workspace; omitido.")
			continue

		for a in anchors:
			if args.remove:
				status = remove_block(path, a, backup=backup)
			else:
				status = splice_block(path, a, bodies[a], _version(a), backup=backup, update=args.update)
			if status not in ("unchanged", "absent"):
				changed += 1
			logger.info(f"✓ {ide}:{a} [{path}] → {status}")

	tail = f" · {reminders} recordatorio(s) de pegado manual" if reminders else ""
	logger.info(f"Hecho. {changed} bloque(s) escrito(s)/modificado(s){tail}.")


if __name__ == "__main__":
	main()
