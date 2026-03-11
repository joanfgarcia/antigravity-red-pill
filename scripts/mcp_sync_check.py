import os
import re
import sys

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

try:
	from red_pill import __version__ as core_version
except ImportError:
	print("❌ Error: Could not import red_pill. Ensure PYTHONPATH is correct.")
	sys.exit(1)


def check_mcp_sync():
	mcp_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "red_pill", "mcp_server.py"))
	if not os.path.exists(mcp_path):
		print(f"❌ Error: mcp_server.py not found at {mcp_path}")
		return False

	with open(mcp_path, "r") as f:
		content = f.read()

	# Check for dynamic version import
	sync_pattern = r"from red_pill import __version__ as CORE_VERSION"
	if not re.search(sync_pattern, content):
		print("❌ Error: mcp_server.py is NOT using dynamic versioning from red_pill.")
		return False

	# Check for InitializationOptions usage
	init_pattern = r"server_version=CORE_VERSION"
	if not re.search(init_pattern, content):
		print("❌ Error: mcp_server.py InitializationOptions are NOT using CORE_VERSION.")
		return False

	print(f"✅ MCP Sync Verified: Core Protocol v{core_version} is properly bound to MCP Server.")
	return True


if __name__ == "__main__":
	if check_mcp_sync():
		sys.exit(0)
	else:
		sys.exit(1)
