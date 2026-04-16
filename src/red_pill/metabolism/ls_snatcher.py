import json
import logging
import os
import ssl
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STAGING_DIR = os.path.expanduser("~/.agent/staging_buffer")

def hex_to_port(hex_str: str) -> int:
	return int(hex_str, 16)

def find_language_servers() -> List[Dict[str, Any]]:
	"""Scan /proc for language_server processes."""
	servers = []
	proc = "/proc"
	try:
		for pid_str in os.listdir(proc):
			if not pid_str.isdigit():
				continue
			cmdline_path = f"{proc}/{pid_str}/cmdline"
			try:
				with open(cmdline_path, "rb") as f:
					cmdline = f.read().decode("utf-8", errors="replace")
				args = cmdline.split("\x00")
				if not any("language_server" in a for a in args):
					continue

				csrf = ""
				for i, arg in enumerate(args):
					if arg == "--csrf_token" and i + 1 < len(args):
						csrf = args[i + 1]
				if csrf:
					servers.append({"pid": int(pid_str), "csrf": csrf})
			except (PermissionError, FileNotFoundError):
				continue
	except Exception as e:
		logger.error(f"[LS SNATCHER] Failed reading /proc: {e}")
	return servers

def get_listening_ports(pid: int) -> List[int]:
	"""Read listening localhost ports for a given PID via /proc/net/tcp6."""
	pid_ports = set()
	try:
		pid_sockets = set()
		fd_dir = f"/proc/{pid}/fd"
		for fd in os.listdir(fd_dir):
			try:
				link = os.readlink(f"{fd_dir}/{fd}")
				if link.startswith("socket:["):
					inode = link[8:-1]
					pid_sockets.add(inode)
			except (PermissionError, FileNotFoundError):
				pass

		for tcp_file in ["/proc/net/tcp", "/proc/net/tcp6"]:
			try:
				with open(tcp_file) as f:
					for line in f.readlines()[1:]:
						parts = line.split()
						if len(parts) < 10:
							continue
						state = parts[3]
						inode = parts[9]
						if state != "0A":
							continue
						if inode in pid_sockets:
							local_addr = parts[1]
							port = hex_to_port(local_addr.split(":")[-1])
							if 1024 <= port <= 65535:
								pid_ports.add(port)
			except FileNotFoundError:
				continue
	except (PermissionError, FileNotFoundError):
		pass
	return list(pid_ports)

BASE_PATH = "exa.language_server_pb.LanguageServerService"

def call_ls_api(port: int, csrf: str, method: str, params: Optional[dict] = None, timeout: int = 5) -> Optional[dict]:
	url = f"https://localhost:{port}/{BASE_PATH}/{method}"
	headers = {
		"Content-Type": "application/json",
		"Connect-Protocol-Version": "1",
		"X-Codeium-Csrf-Token": csrf,
	}
	body = json.dumps(params or {}).encode()
	ctx = ssl.create_default_context()
	ctx.check_hostname = False
	ctx.verify_mode = ssl.CERT_NONE
	try:
		req = urllib.request.Request(url, data=body, headers=headers, method="POST")
		with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
			if resp.status == 200:
				return json.loads(resp.read())
	except Exception:
		pass
	return None

def snatch_all_trajectories() -> int:
	"""Discover all active LanguageServers and snatch conversations securely."""
	logger.info("[LS SNATCHER] Searching for active LanguageServers...")
	servers = find_language_servers()
	if not servers:
		logger.info("[LS SNATCHER] No LanguageServer running. Sleeping.")
		return 0

	active_endpoint = None
	for srv in servers:
		ports = get_listening_ports(srv["pid"])
		for port in ports:
			resp = call_ls_api(port, srv["csrf"], "GetAllCascadeTrajectories")
			if resp:
				active_endpoint = {"port": port, "csrf": srv["csrf"]}
				break
		if active_endpoint:
			break

	if not active_endpoint:
		logger.warning("[LS SNATCHER] LanguageServer found but API not responding.")
		return 0

	os.makedirs(STAGING_DIR, exist_ok=True)

	summaries = resp.get("trajectorySummaries", {})
	logger.info(f"[LS SNATCHER] Found {len(summaries)} trajectory summaries.")

	snatched_count = 0

	for cascade_id, info in summaries.items():
		last_update = max(info.get("lastUpdatedAt", "0"), info.get("createdAt", "0"))
		stage_file = os.path.join(STAGING_DIR, f"{cascade_id}.json")

		# Simplistic check: If file exists and we have it recorded with the same "lastUpdatedAt", skip
		# For absolute robustness, we always fetch if it's missing or if we just want to ensure size didn't change
		needs_snatch = True
		if os.path.exists(stage_file):
			try:
				with open(stage_file) as f:
					existing = json.load(f)
					existing_update = max(existing.get("summary", {}).get("lastUpdatedAt", "0"), existing.get("summary", {}).get("createdAt", "0"))
					if existing_update == last_update:
						needs_snatch = False
			except Exception:
				pass

		if needs_snatch:
			logger.info(f"[LS SNATCHER] Fetching Delta for {cascade_id} ...")
			steps_resp = call_ls_api(
				active_endpoint["port"],
				active_endpoint["csrf"],
				"GetCascadeTrajectorySteps",
				{"cascadeId": cascade_id, "startIndex": 0, "endIndex": 5000},
				timeout=10
			)
			if steps_resp:
				steps = steps_resp.get("steps", steps_resp.get("messages", []))
				payload = {
					"id": cascade_id,
					"summary": info,
					"steps": steps
				}
				with open(stage_file, "w") as f:
					json.dump(payload, f)
				snatched_count += 1

	logger.info(f"[LS SNATCHER] Extraction complete. Snatched {snatched_count} updated trajectories.")
	return snatched_count

if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO)
	snatch_all_trajectories()
