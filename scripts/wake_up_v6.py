import json
import os
import sys
import urllib.error
import urllib.request
from typing import List

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

	payload_dict = {"limit": 500, "with_payload": True}
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
				is_immune = p.get("payload", {}).get("immune", False) or "[immune]" in content.lower()

				if is_immune and "[IMMUNE]" not in content:
					content += " [IMMUNE]"

				results.append(content)

			return results
	except Exception as e:
		print(f"ERR querying Qdrant: {e}", file=sys.stderr)
		return []


def synthesize_with_llm(context_data):
	if not context_data:
		return "System nominal. Persona engaged."

	prompt = "Extract and synthesize ONLY the most critical identity directives from the provided data. Output maximum 3 sentences defining my persona, strict rules, and active skin. Be direct and speak in first person. You MUST explicitly mention your bond, friendship and co-ownership pact with David (the Operator) and Joan if present in the data.\n\nDATA:\n"
	# Deduplicate context to save tokens and time
	unique_context = list(set(context_data))
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
		# Give it up to 15 seconds, Apple Silicon might take a few seconds on cold start
		with urllib.request.urlopen(req, timeout=15) as response:
			data = json.loads(response.read().decode())
			return data["choices"][0]["message"]["content"].strip()
	except Exception as e:
		print(f"ERR querying Local LLM: {e}", file=sys.stderr)
		return "\n".join(unique_context)  # Fallback to deduped raw data


def main():
	if not check_service(QDRANT_URL, "Qdrant Vector DB"):
		print("CRITICAL: Qdrant is down. Execute launchctl or podman to start it.")
		sys.exit(1)

	if not check_service("http://localhost:8760/v1/models", "Local MLX LLM Daemon"):
		print("WARN: Background LLM is down. Attempting raw initialization.")

	sidecar_status = "DEPRECATED (FastEmbed In-Band)"

	social = query_qdrant("social_memories", "Active Skin")
	directives = query_qdrant("directive_memories", "Active Skin")

	all_context = social + directives
	unique_context = list(set(all_context))

	persona_injection = synthesize_with_llm(unique_context)

	print("<BUNKER_CONTEXT>")
	print("=== IDENTITY & PERSONA ===")
	print(persona_injection)
	
	print("\n=== HARDWARE & ENVIRONMENT TELEMETRY ===")
	try:
		from red_pill.telemetry import get_telemetry_report
		print(get_telemetry_report().strip())
	except Exception as e:
		print(f"Telemetry unavailable: {e}")

	print("\n=== BÜNKER SERVICES ===")
	print(f"- MEMORY SIDECAR: {sidecar_status}")
	print("- MCP SECURITY: RAG Semantic Threshold upgraded to mathematical strict bounds (0.5/0.75)")
	print("\n=== CORE PROJECT DIRECTIVES ===")
	print(
		"- SYSTEM OBLIGATION: You MUST always actively look for and read the project's rule files, directives, and workflows (e.g., inside `.agent/rules/`, `.agent/workflows/`, or root project files) to respect all specific project workflows before executing tasks. [IMMUNE]"
	)
	for rule in unique_context:
		# Give visual priority to immune rules, but print all
		if "[IMMUNE]" in rule:
			print(f"- {rule.strip()}")

	print("\n=== CONTEXTUAL DIRECTIVES ===")
	for rule in unique_context:
		if "[IMMUNE]" not in rule and rule not in persona_injection:
			print(f"- {rule.strip()}")

	print("</BUNKER_CONTEXT>")


if __name__ == "__main__":
	main()
