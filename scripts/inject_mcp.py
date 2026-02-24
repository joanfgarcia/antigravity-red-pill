import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("mcp_injector")

def main():
	parser = argparse.ArgumentParser(description="Inject RedPill-Kernel into MCP config")
	parser.add_argument("--uv-path", required=True, help="Absolute path to uv executable")
	parser.add_argument("--redpill-dir", required=True, help="Absolute path to Red Pill source code")

	args = parser.parse_args()

	# Paths to look for config files
	candidates = [
		os.path.expanduser("~/.gemini/antigravity/mcp_config.json"),
		os.path.expanduser("~/.config/Claude/claude_desktop_config.json"),
		os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json"),
		os.path.expanduser("~/AppData/Roaming/Claude/claude_desktop_config.json"),
		os.path.expanduser("~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"),
		os.path.expanduser("~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json")
	]

	mcp_server_path = os.path.join(args.redpill_dir, "src", "red_pill", "mcp_server.py")

	success_count = 0

	for config_file in candidates:
		# Only create if the parent config directory exists (except for Antigravity)
		parent_dir = os.path.dirname(config_file)
		if "antigravity" in config_file:
			os.makedirs(parent_dir, exist_ok=True)
		elif not os.path.exists(parent_dir):
			continue

		config = {}
		if os.path.exists(config_file):
			try:
				with open(config_file, "r", encoding="utf-8") as f:
					config = json.load(f)
			except Exception as e:
				logger.warning(f"Failed to read existing config at {config_file}: {e}. Recreating...")
				config = {}

		if "mcpServers" not in config:
			config["mcpServers"] = {}

		config["mcpServers"]["RedPill-Kernel"] = {
			"command": args.uv_path,
			"args": [
				"--directory",
				args.redpill_dir,
				"run",
				"python",
				mcp_server_path
			]
		}

		try:
			with open(config_file, "w", encoding="utf-8") as f:
				json.dump(config, f, indent=2)
			logger.info(f"✓ RedPill-Kernel MCP config successfully injected at {config_file}")
			success_count += 1
		except Exception as e:
			logger.error(f"Failed to write MCP config to {config_file}: {e}")

	if success_count == 0:
		logger.error("Failed to inject MCP config in any known client directories.")
		sys.exit(1)

if __name__ == "__main__":
	main()
