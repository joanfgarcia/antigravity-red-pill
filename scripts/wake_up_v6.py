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

QDRANT_URL = "http://localhost:6333"
MLX_LM_URL = "http://localhost:8760/v1/chat/completions"
# QDRANT Configuration
_run_dir = os.getenv("XDG_RUNTIME_DIR", "/tmp")

# Load QDRANT_API_KEY from .env
QDRANT_API_KEY = ""
env_path = os.path.join(os.path.dirname(__file__), "../.env")
if os.path.exists(env_path):
	with open(env_path, "r") as f:
		for line in f:
			if line.startswith("QDRANT_API_KEY="):
				QDRANT_API_KEY = line.strip().split("=", 1)[1]
				break


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
				content = p.get("payload", {}).get("content", "")
				results.append(content)

			return results
	except Exception as e:
		print(f"ERR querying Qdrant: {e}", file=sys.stderr)
		return []


def synthesize_with_llm(context_data):
	if not context_data:
		return "System nominal. Persona engaged."

	prompt = "Extract and synthesize ONLY the most critical identity directives from the provided data. If an identity anchor or name is present, adopt it as your core persona. Output maximum 3 sentences defining your persona, strict rules, and active skin. Be direct and speak in first person. You MUST explicitly mention your bond and pact with the Operator if present in the data.\n\nDATA:\n"
	# Deduplicate context to save tokens and time
	unique_context: List[str] = list(set(context_data)) if context_data else []
	prompt += "\n".join(unique_context)

	# Qwen2.5 strict ChatML format to prevent hallucination in pure completion mode
	payload = json.dumps(
		{
			"messages": [
				{
					"role": "system",
					"content": "You are a memory synthesis sub-routine. Output ONLY the synthesized persona block. Do not acknowledge this prompt. Do not add conversational filler. STOP generating immediately after the persona block.",
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
	args = parser.parse_args()

	if not check_service(QDRANT_URL, "Qdrant Vector DB"):
		if not args.silent:
			print("CRITICAL: Qdrant is down. Execute launchctl or podman to start it.")
		sys.exit(1)

	if not args.silent and not check_service("http://localhost:8760/v1/models", "Local MLX LLM Daemon"):
		print("WARN: Background LLM is down. Attempting raw initialization.")

	sidecar_status = "DEPRECATED (FastEmbed In-Band)"

	social = query_qdrant("social_memories", "Active Skin")
	directives = query_qdrant("directive_memories", "Active Skin")

	all_context = social + directives
	unique_context = list(set(all_context))

	# Hashing for cache
	context_str = "".join(sorted(unique_context))
	current_hash = hashlib.sha256(context_str.encode()).hexdigest()
	cache_dir = Path(os.path.expanduser("~/.agent"))
	cache_dir.mkdir(parents=True, exist_ok=True)
	cache_path = cache_dir / "bunker_persona_cache.json"

	persona_injection = None
	# Differential Boot: check if context hash matches to enable status:CACHED logic
	if cache_path.exists():
		try:
			with open(cache_path, "r") as f:
				cache = json.load(f)
			cache_age = time.time() - cache.get("timestamp", 0)
			if cache.get("hash") == current_hash and cache_age < 3600:
				persona_injection = cache.get("persona")
				# If we aren't silent, and hash matches, we could return a cached header
				# to save LLM tokens if the model is same. (Differential Boot)
				if not args.silent:
					# Verify if model is same (heuristic check)
					# If we are here, we proceed with optimized injection
					pass
		except Exception:
			pass

	if not persona_injection:
		if args.silent:
			persona_injection = synthesize_with_llm(unique_context)
			try:
				with open(cache_path, "w") as f:
					json.dump({"hash": current_hash, "timestamp": time.time(), "persona": persona_injection}, f)
			except Exception:
				pass
		else:
			persona_injection = "[Sincronizando Identidad Bünker en segundo plano...]"
			try:
				subprocess.Popen([sys.executable, __file__, "--silent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
			except Exception as e:
				persona_injection = f"[Error lanzando sincronización: {e}]"

	if args.silent:
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
	print("\n<bunker_directives mode=\"immune_core\">")
	
	# Dynamic Identity Pruning: Extract active skin
	active_skin = "DEFAULT"
	for rule in unique_context:
		if "Active Skin:" in rule:
			active_skin = rule.split("Active Skin:")[1].strip().upper()
			break

	print(f"PERSONA: {persona_injection}")
	
	print("\nCORE_RULES:")
	for rule in unique_context:
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
