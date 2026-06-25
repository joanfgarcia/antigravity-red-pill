import argparse
import json
import logging
import os
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("mcp_injector")

# Shared placeholder helpers live alongside this script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config_common import build_vars, subst  # noqa: E402


# ── Target discovery (cross-platform IDE / CLI MCP config files) ──────────────
def discover_targets(workspace=None):
	"""Return the MCP config files that exist on this machine, plus seeds for
	Antigravity and (if a workspace is given) the Claude Code project scope."""
	candidates = [
		"~/.gemini/config/mcp_config.json",  # Antigravity 2.x (real path)
		"~/.gemini/antigravity/mcp_config.json",  # Antigravity (legacy/alt layout)
		"~/.config/Claude/claude_desktop_config.json",  # Claude Desktop (Linux)
		"~/Library/Application Support/Claude/claude_desktop_config.json",  # Claude Desktop (macOS)
		"~/AppData/Roaming/Claude/claude_desktop_config.json",  # Claude Desktop (Windows)
		"~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
		"~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json",
		"~/.claude.json",  # Claude Code (User level CLI config)
	]
	targets = [os.path.expanduser(c) for c in candidates if os.path.exists(os.path.expanduser(c))]

	# Antigravity: if no config exists yet, seed the canonical 2.x path (not the legacy one).
	gemini = os.path.expanduser("~/.gemini")
	if os.path.isdir(gemini) and not any(".gemini" in t for t in targets):
		targets.append(os.path.join(gemini, "config", "mcp_config.json"))

	# Claude Code (this CLI): project-scoped .mcp.json lives in the workspace root.
	if workspace:
		targets.append(os.path.join(os.path.expanduser(workspace), ".mcp.json"))

	return targets


def load_manifest_servers(path, variables):
	with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
		manifest = json.load(f)
	servers = manifest.get("mcps") or manifest.get("mcpServers") or {}
	return {name: subst(defn, variables) for name, defn in servers.items()}


def redpill_server(uv_path, redpill_dir):
	"""RedPill-Kernel uses 'uv --directory' by canonical convention (see inject history)."""
	mcp_server_path = os.path.join(redpill_dir, "src", "red_pill", "mcp_server.py")
	return {
		"command": uv_path,
		"args": ["--directory", redpill_dir, "run", "python", mcp_server_path],
	}


# ── Merge logic: assert some servers, skip-if-exists for the rest ─────────────
def inject(config_file, servers, assert_names=frozenset(), update=False, backup=True):
	"""Merge `servers` (name -> definition) into config_file's mcpServers.
	- assert_names: always written (RedPill-Kernel self-heal).
	- everything else: SKIPPED if the key already exists, unless --update.
	Never removes or rewrites unrelated entries. Returns True if the file changed."""
	config = {}
	if os.path.exists(config_file):
		try:
			with open(config_file, "r", encoding="utf-8") as f:
				config = json.load(f)
		except Exception as exc:
			logger.warning(f"Unreadable config at {config_file}: {exc}. Recreating.")
			config = {}

	mcps = config.setdefault("mcpServers", {})
	added, updated, skipped = [], [], []
	for name, defn in servers.items():
		exists = name in mcps
		force = name in assert_names or update
		if exists and not force:
			skipped.append(name)
			continue
		mcps[name] = defn
		(updated if exists else added).append(name)

	if not added and not updated:
		logger.info(f"• {config_file}: sin cambios (ya presentes: {', '.join(skipped) or 'ninguno'})")
		return False

	os.makedirs(os.path.dirname(config_file), exist_ok=True)
	if backup and os.path.exists(config_file):
		shutil.copy2(config_file, config_file + ".bak")
	with open(config_file, "w", encoding="utf-8") as f:
		json.dump(config, f, indent=2, ensure_ascii=False)
		f.write("\n")
	logger.info(f"✓ {config_file}: added={added or '∅'} updated={updated or '∅'} skipped={skipped or '∅'}")
	return True


def main():
	parser = argparse.ArgumentParser(description="Inject MCP servers (RedPill-Kernel and/or an external bundle) into IDE/CLI configs.")
	parser.add_argument("--uv-path", help="Absolute path to uv (for RedPill-Kernel). Autodetected if omitted.")
	parser.add_argument("--redpill-dir", help="Absolute path to Red Pill source — enables RedPill-Kernel injection.")
	parser.add_argument("--manifest", help="External MCP bundle manifest (JSON). Injected skip-if-exists.")
	parser.add_argument("--workspace", help="Workspace root: resolves ${WORKSPACE} and targets Claude Code .mcp.json.")
	parser.add_argument("--update", action="store_true", help="Overwrite manifest MCPs even if they already exist.")
	parser.add_argument("--no-backup", action="store_true", help="Do not write a .bak before modifying.")
	args = parser.parse_args()

	if not args.redpill_dir and not args.manifest:
		parser.error("nada que hacer: pasa --redpill-dir y/o --manifest")

	variables = build_vars(args)
	servers = {}
	assert_names = set()

	if args.redpill_dir:
		uv_path = args.uv_path or variables["UV"]
		if not uv_path:
			parser.error("--uv-path no dado y 'uv' no está en el PATH")
		servers["RedPill-Kernel"] = redpill_server(uv_path, args.redpill_dir)
		assert_names.add("RedPill-Kernel")  # red-pill asegura siempre su propia entrada

	if args.manifest:
		servers.update(load_manifest_servers(args.manifest, variables))

	targets = discover_targets(args.workspace)
	if not targets:
		logger.error("No se encontró ninguna config de cliente MCP donde inyectar.")
		sys.exit(1)

	changed = sum(inject(t, servers, assert_names=assert_names, update=args.update, backup=not args.no_backup) for t in targets)
	logger.info(f"Hecho. {changed}/{len(targets)} config(s) modificada(s).")


if __name__ == "__main__":
	main()
