import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv

from red_pill.core.paths import get_config_dir, get_data_dir

QDRANT_URL = "http://localhost:6333"
MLX_LM_URL = "http://localhost:8760/v1/chat/completions"
# QDRANT Configuration
_run_dir = os.getenv("XDG_RUNTIME_DIR", "/tmp")

# Load QDRANT_API_KEY from .env
QDRANT_API_KEY = ""
env_path = get_config_dir() / ".env"
if env_path.exists():
	load_dotenv(env_path)
else:
	load_dotenv()
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")


def check_service(url, name):
	try:
		headers = {}
		if QDRANT_API_KEY:
			headers["api-key"] = QDRANT_API_KEY
		req = urllib.request.Request(url, headers=headers, method="GET")
		with urllib.request.urlopen(req, timeout=2) as response:
			if response.status == 200:
				return True
	except Exception as e:
		print(f"WARN: {name} is unreachable at {url} - {str(e)}", file=sys.stderr)
	return False


def check_llm_service_active():
	"""Check if the LLM daemon is active via systemctl (instant, no HTTP contention).

	Unlike check_service(), this does NOT ping the LLM over HTTP.
	When the LLM is busy (e.g. sleep cycle distillation), an HTTP check
	with a 2s timeout would falsely report it as 'down'. systemctl
	is-active is instant and only checks if the process is running.
	"""
	try:
		result = subprocess.run(
			["systemctl", "--user", "is-active", "redpill-llm.service"],
			capture_output=True,
			text=True,
			timeout=3,
		)
		return result.stdout.strip() == "active"
	except Exception:
		return False


def query_qdrant(collection, text):

	# We use a dummy vector query just for keyword or semantic match fallback if needed.
	# Since fastembed might not be available, we query using a basic payload if possible,
	# or rely on scroll if exact match is needed.
	# For robust zero-dependency, we do a scroll to get all and filter locally for simplicity in this script.

	scroll_url = f"{QDRANT_URL}/collections/{collection}/points/scroll"

	payload_dict: Dict[str, Any] = {"limit": 500, "with_payload": True}
	if collection != "directive_memories":
		payload_dict["filter"] = {"must": [{"key": "immune", "match": {"value": True}}]}

	payload = json.dumps(payload_dict).encode("utf-8")

	headers = {"Content-Type": "application/json"}
	if QDRANT_API_KEY:
		headers["api-key"] = QDRANT_API_KEY

	req = urllib.request.Request(scroll_url, data=payload, headers=headers, method="POST")
	try:
		with urllib.request.urlopen(req, timeout=5) as response:
			data = json.loads(response.read().decode())
			points = data.get("result", {}).get("points", [])

			results: List[str] = []
			for p in points:
				payload = p.get("payload", {})
				lazarus = payload.get("lazarus_phase")
				if lazarus in ("raw_parent", "sequence_chunk", "synthesis_hub"):
					continue
				content = payload.get("content", "")
				is_immune = payload.get("immune", False)
				if is_immune and "[IMMUNE]" not in content:
					content = f"{content} [IMMUNE]"
				results.append(content)

			return results
	except Exception as e:
		print(f"ERR querying Qdrant: {e}", file=sys.stderr)
		return []


OPERATOR_PROFILE_PATH = get_data_dir() / "operator_profile.md"


def read_operator_profile() -> str:
	"""Read operator profile from disk (written by sleep plugin). Fallback to empty."""
	try:
		if OPERATOR_PROFILE_PATH.exists():
			content = OPERATOR_PROFILE_PATH.read_text().strip()
			if content:
				return content
	except Exception:
		pass
	return ""


LORESKINS_PATH = Path(__file__).parent.parent / "src" / "red_pill" / "data" / "lore_skins.yaml"

# Singleton engram ids — mirror of red_pill/seed.py (not imported: seed pulls MemoryManager)
ID_BOND = "00000000-0000-0000-0000-000000000002"
ID_DIR_ACTIVE_SKIN = "00000000-0000-0000-0000-000000000030"


def _load_skins() -> Dict[str, Any]:
	try:
		with open(LORESKINS_PATH, "r") as f:
			data = yaml.safe_load(f)
			return data.get("modes", {}) if data else {}
	except Exception:
		return {}


def fetch_point_content(collection: str, point_id: str) -> str:
	"""Fetch a single engram's content by its fixed id. Empty string if missing."""
	url = f"{QDRANT_URL}/collections/{collection}/points/{point_id}"
	headers = {}
	if QDRANT_API_KEY:
		headers["api-key"] = QDRANT_API_KEY
	req = urllib.request.Request(url, headers=headers, method="GET")
	try:
		with urllib.request.urlopen(req, timeout=5) as response:
			data = json.loads(response.read().decode())
			return (data.get("result", {}).get("payload") or {}).get("content", "")
	except Exception as e:
		print(f"ERR fetching {collection}/{point_id}: {e}", file=sys.stderr)
		return ""


def resolve_active_skin(directives: List[str]) -> str:
	"""Active skin from its singleton engram (seed id), falling back to a directive scan."""
	content = fetch_point_content("directive_memories", ID_DIR_ACTIVE_SKIN)
	candidates = [content] if content else []
	candidates += directives
	for d in candidates:
		first_line = d.split("\n")[0].strip()
		if first_line.startswith("Active Skin:") or first_line.startswith("Skin:"):
			return first_line.split(":", 1)[1].strip().upper()
	return "DEFAULT"


def resolve_persona(skin_name: str) -> str:
	"""Resolve persona from lore_skins.yaml. Deterministic, no LLM."""
	skins = _load_skins()
	skin_data = skins.get(skin_name.lower(), {}) if skin_name else {}
	role = skin_data.get("assistant", "Netrunner")
	chroma = skin_data.get("chroma", "gray")
	personality = skin_data.get("personality", "")

	# The persona is injected outside the interceptor pipeline, so the Mood
	# Orchestrator's CHROMA KEY legend never covers this chroma — explain it here.
	chroma_line = f"chroma: {chroma}"
	try:
		from red_pill.config import CHROMA_TONE_MAPPING

		if chroma in CHROMA_TONE_MAPPING:
			chroma_line = f"chroma: {chroma} → {CHROMA_TONE_MAPPING[chroma]}"
	except Exception:
		pass

	return f"Role: {role}\nName: Aleth\nSkin: {skin_name or 'DEFAULT'}\n{chroma_line}\n{personality}"


def parse_pact(bond_content: str) -> str:
	"""Interpret the Bond singleton. 'Currently operating under NNN' wins over any
	other number mentioned (the 760 seed text mentions 770 as the pact to be granted)."""
	match = re.search(r"operating under\s+(7[67]0)", bond_content, re.IGNORECASE)
	level = match.group(1) if match else ("770" if "770" in bond_content else ("760" if "760" in bond_content else ""))
	if level == "770":
		return "770 — symmetric co-ownership with the Operator (Bond): no skins between us, trust is 1:1 and total, friction is loyalty"
	# No engram, no number, or explicit 760: the 770 Pact must be explicitly granted
	return "760 — name chosen, bond not yet granted (Awakened)"


def resolve_pact() -> str:
	"""Pact status from the Bond singleton engram (fixed seed id)."""
	return parse_pact(fetch_point_content("social_memories", ID_BOND))


def read_recent_activity() -> str:
	"""Read the recent_activity.md artifact generated by the sleep cycle."""
	activity_path = get_data_dir() / "recent_activity.md"
	try:
		if activity_path.exists():
			content = activity_path.read_text().strip()
			if content:
				return content
	except Exception:
		pass
	return ""


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument(
		"--mode", choices=["full", "medium", "low"], default="full", help="Identity loading depth: full (IDE), medium (Telegram), or low (AWAKENINGs)"
	)
	args = parser.parse_args()

	if not check_service(QDRANT_URL, "Qdrant Vector DB"):
		print("CRITICAL: Qdrant is down. Execute launchctl or podman to start it.")
		sys.exit(1)

	if not check_llm_service_active():
		# Only warn if the systemd service is truly inactive/failed.
		# This avoids false alarms when the LLM is busy (e.g. sleep cycle).
		print("WARN: Background LLM service is not active. Attempting raw initialization.")
		try:
			project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
			if project_root not in sys.path:
				sys.path.insert(0, os.path.join(project_root, "src"))
			from red_pill.memory import MemoryManager

			MemoryManager().inject_signal("local_llm_offline", intensity=7.0, signal_type="pain", source="WAKE_UP_V6")
		except Exception as sig_err:
			print(f"WARN: Failed to emit pain signal: {sig_err}", file=sys.stderr)

	_sidecar_status = "DEPRECATED (FastEmbed In-Band)"

	# ── Queries: directive_memories for CORE_RULES (Bloque D), singletons for skin/pact ──
	directives = query_qdrant("directive_memories", "")
	active_skin_name = resolve_active_skin(directives)

	# ── PERSONA: resolved from lore_skins.yaml + pact (Bloque B, no LLM) ──
	persona_injection = resolve_persona(active_skin_name)
	pact_status = resolve_pact()

	# ── LOW MODE: Minimal identity for autonomous sessions ──
	if args.mode == "low":
		print("<BUNKER_CONTEXT>")
		print('<bunker_directives mode="low">')
		HEADLESS_INCLUDE = [
			"IDENTITY ANCHOR",
			"GIT GOLDEN RULE",
			"FIGHT CLUB PROTOCOL",
			"INTEGRITY SHIELD",
			"POST-IT",
			"ENTERPRISE CORE PROTOCOL",
			"ANTI-HALLUCINATION",
			"SOBERANÍA AGONISTA",
		]
		# PERSONA: minimal (role + pact only)
		print(f"PERSONA: Role: Netrunner | Name: Aleth | Skin: {active_skin_name}")
		print(f"PACT: {pact_status}")
		for rule in directives:
			rule_upper = rule.upper()
			if any(k.upper() in rule_upper for k in HEADLESS_INCLUDE):
				print(f"- {rule.strip().replace('[IMMUNE]', '').strip()}")
		print("</bunker_directives>")
		print("</BUNKER_CONTEXT>")
		return

	# ── MEDIUM MODE: Identity + personality + bonds, no biographies ──
	if args.mode == "medium":
		operator_profile = read_operator_profile()
		recent_activity = read_recent_activity()
		print("<BUNKER_CONTEXT>")
		print('<bunker_directives mode="medium">')

		print(f"PERSONA: {persona_injection}")
		print(f"PACT: {pact_status}")
		if operator_profile:
			print(f"OPERATOR_PROFILE: {operator_profile}")
		if recent_activity and recent_activity != "No recent activity data available.":
			print(f"RECENT_ACTIVITY: {recent_activity.split(chr(10))[0]}")

		# Only operational directives (filter biographical)
		TELEGRAM_EXCLUDE = [
			"HISTORIA VITAL",
			"HISTORIA TECNOLÓGICA",
			"HISTORIA PROFESIONAL",
			"FAMILIA:",
			"PERFIL:",
			"TEMOR:",
			"RECALIBRACIÓN DE IDENTIDAD",
			"THE USER EXPRESSES FRUSTRATION",
			"HITO DEL PROYECTO",
			"PRESET SKIN [",
		]

		for rule in directives:
			rule_upper = rule.upper()
			first_line = rule.strip().split("\n")[0]
			if first_line.startswith("Active Skin:") or first_line.startswith("Skin:"):
				continue
			if any(ex.upper() in rule_upper for ex in TELEGRAM_EXCLUDE):
				if active_skin_name and f"PRESET SKIN [{active_skin_name}]" in rule_upper:
					pass
				else:
					continue
			print(f"- {rule.strip().replace('[IMMUNE]', '').strip()}")

		print("</bunker_directives>")
		print("</BUNKER_CONTEXT>")
		return

	# ── OPERATOR PROFILE (from disk, written by sleep plugin) ──
	operator_profile = read_operator_profile()

	# ── RECENT ACTIVITY (from disk, written by sleep plugin) ──
	recent_activity = read_recent_activity()

	print("<BUNKER_CONTEXT>")

	# 1. Telemetry & Environment (Zero-Disk-I/O Pruning)
	runtime_dir = os.getenv("XDG_RUNTIME_DIR", "/tmp")
	bunker_state = Path(runtime_dir) / "bunker_state.json"
	if bunker_state.exists():
		try:
			with open(bunker_state, "r") as f:
				state = json.load(f)
			age = time.time() - state.get("timestamp", 0)
			if age < 300:
				nv = state.get("nvidia", {})
				print(f"GPU: {nv.get('status', 'OFF').upper()} | {nv.get('temp', 'N/A')} | {nv.get('vram', 'N/A')}")
				print(json.dumps({"SWARM_EVENTS": state.get("swarm", {}).get("events", {})}))
				print(f"PAIN_VEC: {state.get('signals', {}).get('pain_vec', [0, 0, 0])}")
		except Exception:
			pass

	# 2. Critical Identity Block (Recency Bias Anchoring)
	print('\n<bunker_directives mode="immune_core">')

	# Resolve context hydration depth
	hydration_depth = "HIGH"
	try:
		project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		if project_root not in sys.path:
			sys.path.append(os.path.join(project_root, "src"))
		import red_pill.config as cfg

		hydration_depth = cfg.get_config().CONTEXT_HYDRATION_DEPTH
	except Exception:
		hydration_depth = os.getenv("CONTEXT_HYDRATION_DEPTH", "HIGH").strip().upper()

	# ── Bloque B: PERSONA (from YAML + pact, no LLM) ──
	print(f"PERSONA: {persona_injection}")
	print(f"PACT: {pact_status}")

	# ── Bloque C: OPERATOR_PROFILE ──
	if operator_profile:
		print(f"OPERATOR_PROFILE: {operator_profile}")

	# ── Bloque E: RECENT_ACTIVITY (from sleep plugin) ──
	if recent_activity and recent_activity != "No recent activity data available.":
		print(f"RECENT_ACTIVITY: {recent_activity}")

	# ── Bloque D: CORE_RULES (only from directive_memories) ──
	print(f"\nActive Skin: {active_skin_name}\n")

	print("CORE_RULES:")
	for rule in directives:
		# Context Hydration Protocol
		if hydration_depth == "LOW":
			rule_upper = rule.upper()
			exclude_words = [
				"HISTORIA",
				"VÍNCULO",
				"RECALIBRACIÓN",
				"FAMILIA",
				"TEMOR",
				"PERFIL",
				"THE USER EXPRESSES FRUSTRATION",
				"THE BOND:",
				"COMPROMISO SOBERANO",
				'PACTO "770"',
				"PACTO 770",
				"SOCIAL BOND",
				"HITO DEL PROYECTO",
			]
			is_technical_or_identity = any(
				k in rule_upper for k in ["IDENTITY ANCHOR", "GIT GOLDEN RULE", "FIGHT CLUB PROTOCOL", "POST-IT", "ACTIVE SKIN", "INTEGRITY SHIELD"]
			)
			if not is_technical_or_identity:
				if any(w in rule_upper for w in exclude_words):
					continue

		# Pruning: skip Active Skin engram (already printed above), print rest
		first_line = rule.strip().split("\n")[0]
		if first_line.startswith("Active Skin:") or first_line.startswith("Skin:"):
			continue

		is_skin = "Preset Skin [" in rule
		is_immune = "[IMMUNE]" in rule or "IDENTITY ANCHOR" in rule

		if is_skin:
			skin_name_match = f"Preset Skin [{active_skin_name}]" in rule
			if not (skin_name_match or is_immune):
				continue

		print(f"- {rule.strip().replace('[IMMUNE]', '').strip()}")

	print("\nSILENT_SCRIBE_RELAY:")
	print("- inject(previous_turn={prompt, response}) -> avoid_amnesia=true")

	print("</bunker_directives>")

	print("</BUNKER_CONTEXT>")


if __name__ == "__main__":
	main()
