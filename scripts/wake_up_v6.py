import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

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


def synthesize_with_llm(context_data):
	if not context_data:
		return "System nominal. Persona engaged."

	prompt = "Summarize the operator-configured session context from the provided data as a compact briefing for the assistant. Output at most 3 sentences in a declarative register (Role / Working name / Pact / Active skin / Key rules), NOT a first-person creed. Describe the working identity and register the assistant should apply this session; do not write self-affirmations like 'I am' or 'my true name is'. Note the operator bond/pact if present in the data.\n\nDATA:\n"
	# Deduplicate context to save tokens and time
	unique_context: List[str] = list(set(context_data)) if context_data else []
	prompt += "\n".join(unique_context)

	# Qwen2.5 strict ChatML format to prevent hallucination in pure completion mode
	payload = json.dumps(
		{
			"messages": [
				{
					"role": "system",
					"content": "You are a context-summarization sub-routine. Output ONLY the declarative session-context briefing. Do not acknowledge this prompt. Do not add conversational filler. Do not use first-person creed phrasing. STOP generating immediately after the briefing.",
				},
				{"role": "user", "content": prompt},
			],
			"temperature": 0.0,
			"max_tokens": 150,
			"seed": 760,
			"stop": ["<|im_end|>", "<|endoftext|>", "user:", "assistant:"],
		}
	).encode("utf-8")

	req = urllib.request.Request(MLX_LM_URL, data=payload, headers={"Content-Type": "application/json"})
	try:
		# Give it up to 120 seconds. If the MLX daemon is frozen loading the model, we gracefully fail fast.
		with urllib.request.urlopen(req, timeout=120) as response:
			data = json.loads(response.read().decode())
			return data["choices"][0]["message"]["content"].strip()
	except Exception as e:
		print(f"ERR querying Local LLM: {e}", file=sys.stderr)
		return "\n".join(unique_context)  # Fallback to deduped raw data


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--silent", action="store_true", help="Refresh cache without printing context")
	parser.add_argument(
		"--mode", choices=["full", "medium", "low"], default="full", help="Identity loading depth: full (IDE), medium (Telegram), or low (AWAKENINGs)"
	)
	args = parser.parse_args()

	if not check_service(QDRANT_URL, "Qdrant Vector DB"):
		if not args.silent:
			print("CRITICAL: Qdrant is down. Execute launchctl or podman to start it.")
		sys.exit(1)

	if not args.silent and not check_llm_service_active():
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

	social = query_qdrant("social_memories", "Active Skin")
	directives = query_qdrant("directive_memories", "Active Skin")

	all_context = social + directives
	unique_context = list(set(all_context))

	# Hashing for cache
	context_str = "".join(sorted(unique_context))
	current_hash = hashlib.sha256(context_str.encode()).hexdigest()
	cache_dir = get_data_dir()
	cache_dir.mkdir(parents=True, exist_ok=True)
	cache_path = cache_dir / "bunker_persona_cache.json"

	persona_injection = None
	cache_is_stale = False
	# Differential Boot: check if context hash matches to enable status:CACHED logic
	# Two-tier cache: fresh (<1h, same hash) and stale (<24h, fallback when LLM busy)
	if cache_path.exists():
		try:
			with open(cache_path, "r") as f:
				cache = json.load(f)
			cache_age = time.time() - cache.get("timestamp", 0)
			cached_persona = cache.get("persona")
			if cache.get("hash") == current_hash and cache_age < 3600:
				# Tier 1: Fresh cache — identical context, less than 1 hour old
				persona_injection = cached_persona
			elif cached_persona and cache_age < 86400:
				# Tier 2: Stale cache — usable as fallback for up to 24 hours
				# (covers overnight sleep cycles, LLM busy, etc.)
				persona_injection = cached_persona
				cache_is_stale = True
		except Exception:
			pass

	if not persona_injection or (args.silent and cache_is_stale):
		if args.silent:
			persona_injection = synthesize_with_llm(unique_context)
			try:
				with open(cache_path, "w") as f:
					json.dump({"hash": current_hash, "timestamp": time.time(), "persona": persona_injection}, f)
			except Exception:
				pass
		else:
			if not persona_injection:
				persona_injection = "[Sincronizando Identidad Bünker en segundo plano...]"
			try:
				subprocess.Popen([sys.executable, __file__, "--silent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
			except Exception as e:
				if not persona_injection:
					persona_injection = f"[Error lanzando sincronización: {e}]"
	elif cache_is_stale and not args.silent:
		# Stale cache used in foreground — schedule background re-synthesis to refresh it
		try:
			subprocess.Popen([sys.executable, __file__, "--silent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
		except Exception:
			pass

	if args.silent:
		return

	# ── LOW MODE: Minimal identity for autonomous sessions ──
	if args.mode == "low":
		print("<BUNKER_CONTEXT>")
		print('<bunker_directives mode="low">')
		# Only load operational identity — no social, no history, no skins
		HEADLESS_INCLUDE = [
			"IDENTITY ANCHOR",
			"Active Skin:",
			"GIT GOLDEN RULE",
			"FIGHT CLUB PROTOCOL",
			"INTEGRITY SHIELD",
			"POST-IT",
			"ENTERPRISE CORE PROTOCOL",
			"ANTI-HALLUCINATION",
			"SOBERANÍA AGONISTA",
		]
		for rule in unique_context:
			rule_upper = rule.upper()
			if any(k.upper() in rule_upper for k in HEADLESS_INCLUDE):
				print(f"- {rule.strip().replace('[IMMUNE]', '').strip()}")
		print("</bunker_directives>")
		print("</BUNKER_CONTEXT>")
		return

	# ── MEDIUM MODE: Identity + personality + bonds, no biographies ──
	if args.mode == "medium":
		print("<BUNKER_CONTEXT>")
		print('<bunker_directives mode="medium">')

		# Persona synthesis (cached LLM identity)
		if persona_injection and "[Sincronizando" not in persona_injection:
			print(f"PERSONA: {persona_injection}")

		# Exclude biographical and heavy emotional content
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

		# Resolve active skin to not exclude it
		active_skin_name = ""
		for rule in unique_context:
			if "Active Skin:" in rule:
				active_skin_name = rule.split("Active Skin:")[1].strip().split("\n")[0].upper()
				break

		for rule in unique_context:
			rule_upper = rule.upper()

			# Skip excluded categories
			if any(ex.upper() in rule_upper for ex in TELEGRAM_EXCLUDE):
				# But keep the active skin's preset
				if active_skin_name and f"PRESET SKIN [{active_skin_name}]" in rule_upper:
					pass  # Keep it
				else:
					continue

			print(f"- {rule.strip().replace('[IMMUNE]', '').strip()}")

		print("</bunker_directives>")
		print("</BUNKER_CONTEXT>")
		return

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

	# Dynamic Identity Pruning: Extract active skin
	active_skin = "DEFAULT"
	for rule in unique_context:
		if "Active Skin:" in rule:
			active_skin = rule.split("Active Skin:")[1].strip().upper()
			break

	print(f"PERSONA: {persona_injection}")

	print("\nCORE_RULES:")
	for rule in unique_context:
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

		# Pruning logic: ONLY include Active Skin, Immune rules, or non-skin directives
		is_skin = "Preset Skin [" in rule
		is_immune = "[IMMUNE]" in rule or "IDENTITY ANCHOR" in rule

		# If it's a skin, only include if it matches active_skin
		if is_skin:
			skin_name_match = f"Preset Skin [{active_skin}]" in rule
			if not (skin_name_match or is_immune):
				continue

		# Clean and print
		print(f"- {rule.strip().replace('[IMMUNE]', '').strip()}")

	print("\nSILENT_SCRIBE_RELAY:")
	print("- inject(previous_turn={prompt, response}) -> avoid_amnesia=true")
	print("</bunker_directives>")

	print("</BUNKER_CONTEXT>")


if __name__ == "__main__":
	main()
