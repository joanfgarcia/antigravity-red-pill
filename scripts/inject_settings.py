"""Merge red-pill's settings fragment into a Claude Code settings.json.

Third sibling of ``inject_mcp.py`` / ``inject_anchor.py``. Where inject_mcp merges
MCP servers and inject_anchor merges Markdown anchor blocks, this merges a
``permissions`` fragment (chiefly ``additionalDirectories``) so the agent can
reach its transversal directories (Agent_Core, atlas, XDG) that live OUTSIDE the
project workspace.

Guest principle (same as the others): deep-merge, never overwrite. Arrays under
``permissions`` are unioned (append + dedupe); every unrelated key is preserved.

SECURITY: this never writes ``defaultMode``/``bypassPermissions``. Autonomous
permission bypass is a per-launch CLI flag for the headless awakening runner
(``claude --permission-mode bypassPermissions``), so it never leaks into the
operator's interactive session via a shared settings.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("settings_injector")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config_common import agent_core_vars, build_vars, subst, workspace_access_dirs  # noqa: E402

PERMISSION_LIST_KEYS = ("allow", "ask", "deny", "additionalDirectories")


def _strip_comments(value):
	"""Drop keys starting with '_' (doc comments in the seed)."""
	if isinstance(value, dict):
		return {k: _strip_comments(v) for k, v in value.items() if not k.startswith("_")}
	if isinstance(value, list):
		return [_strip_comments(v) for v in value]
	return value


def _union(existing, incoming):
	out = list(existing or [])
	for item in incoming or []:
		if item not in out:
			out.append(item)
	return out


def deep_merge(base, frag):
	"""Recursively merge frag into base. Lists are unioned (dedupe, order-preserving)."""
	for key, val in frag.items():
		if isinstance(val, dict) and isinstance(base.get(key), dict):
			deep_merge(base[key], val)
		elif isinstance(val, list):
			base[key] = _union(base.get(key), val)
		else:
			base[key] = val
	return base


def remove_fragment(settings, frag):
	"""Remove only the fragment's own list items; leave everything else intact."""
	perms_f = frag.get("permissions", {})
	perms_s = settings.get("permissions")
	if isinstance(perms_s, dict):
		for key in PERMISSION_LIST_KEYS:
			if key in perms_f and isinstance(perms_s.get(key), list):
				drop = set(perms_f[key])
				perms_s[key] = [x for x in perms_s[key] if x not in drop]
				if not perms_s[key]:
					del perms_s[key]
		if not perms_s:
			del settings["permissions"]
	return settings


def _load_json(path):
	if not os.path.exists(path):
		return {}
	try:
		with open(path, encoding="utf-8") as f:
			return json.load(f)
	except Exception as exc:
		logger.warning(f"settings.json ilegible en {path}: {exc}. Se recrea.")
		return {}


def _atomic_write(path, data, backup=True):
	parent = os.path.dirname(os.path.abspath(path))
	os.makedirs(parent, exist_ok=True)
	if backup and os.path.exists(path):
		shutil.copy2(path, path + ".bak")
	tmp = path + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump(data, f, indent=2, ensure_ascii=False)
		f.write("\n")
	os.replace(tmp, path)


def resolve_target(args):
	if args.target:
		return os.path.expanduser(args.target)
	if args.workspace:
		return os.path.join(os.path.expanduser(args.workspace), ".claude", "settings.json")
	return os.path.expanduser("~/.claude/settings.json")


def main():
	parser = argparse.ArgumentParser(
		description="Merge red-pill's permissions fragment into a Claude Code settings.json."
	)
	parser.add_argument("--target", help="settings.json path. Default ~/.claude/settings.json.")
	parser.add_argument("--workspace", help="If set (and no --target), targets <ws>/.claude/settings.json.")
	parser.add_argument("--seed", help="Fragment seed path. Default seeds/settings/claude-code.json.")
	parser.add_argument("--redpill-dir", help="Red Pill source dir (resolves ${REDPILL_DIR}).")
	parser.add_argument("--uv-path", help="Path to uv (shared build_vars).")
	parser.add_argument("--no-backup", action="store_true", help="Do not write a .bak before modifying.")
	parser.add_argument("--remove", action="store_true", help="Remove the fragment's entries instead of merging.")
	parser.add_argument("--extra-dir", action="append", default=[], help="Extra directory to add (or, with --remove, to remove). Repeatable.")
	parser.add_argument("--print", dest="print_only", action="store_true", help="Resolve and print additionalDirectories; do not write.")
	args = parser.parse_args()

	seed = os.path.expanduser(args.seed) if args.seed else os.path.join(
		os.path.dirname(os.path.abspath(__file__)), "..", "seeds", "settings", "claude-code.json"
	)
	seed = os.path.abspath(seed)
	if not os.path.exists(seed):
		parser.error(f"seed no encontrado: {seed}")

	variables = build_vars(args)
	variables.update(agent_core_vars())
	with open(seed, encoding="utf-8") as f:
		fragment = _strip_comments(subst(json.load(f), variables))

	# ADD path: augment the seed (transversal) fragment with registry-derived workspace dirs
	# (access: true) + any explicit --extra-dir. The REMOVE path keeps the fragment narrow.
	if not args.remove:
		extra = list(workspace_access_dirs()) + [os.path.expanduser(d) for d in args.extra_dir]
		if extra:
			ad = fragment.setdefault("permissions", {}).setdefault("additionalDirectories", [])
			for d in extra:
				if d not in ad:
					ad.append(d)

	if args.print_only:
		for d in fragment.get("permissions", {}).get("additionalDirectories", []):
			print(d)
		return

	target = resolve_target(args)
	before = _load_json(target)
	after = json.loads(json.dumps(before))  # deep copy
	if args.remove:
		# Targeted removal (e.g. `workspace disable`): drop ONLY the explicit dirs, never the
		# transversal seed or other still-enabled workspaces. Without --extra-dir, remove the
		# whole fragment (full uninstall).
		if args.extra_dir:
			drop = {"permissions": {"additionalDirectories": [os.path.expanduser(d) for d in args.extra_dir]}}
			remove_fragment(after, drop)
		else:
			remove_fragment(after, fragment)
	else:
		deep_merge(after, fragment)

	if after == before:
		logger.info(f"• {target}: sin cambios.")
		return
	_atomic_write(target, after, backup=not args.no_backup)
	action = "limpiado" if args.remove else "mergeado"
	dirs = fragment.get("permissions", {}).get("additionalDirectories", [])
	logger.info(f"✓ {target}: fragmento {action}. additionalDirectories: {dirs}")


if __name__ == "__main__":
	main()
