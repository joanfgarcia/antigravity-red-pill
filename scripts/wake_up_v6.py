import os
import sys
import json
import urllib.request
import urllib.error

QDRANT_URL = "http://localhost:6333"
MLX_LM_URL = "http://localhost:8080/v1/chat/completions"

def check_service(url, name):
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            if response.status == 200:
                return True
    except Exception as e:
        print(f"WARN: {name} is unreachable at {url} - {str(e)}", file=sys.stderr)
    return False

def query_qdrant(collection, text):
    url = f"{QDRANT_URL}/collections/{collection}/points/query"
    
    # We use a dummy vector query just for keyword or semantic match fallback if needed.
    # Since fastembed might not be available, we query using a basic payload if possible,
    # or rely on scroll if exact match is needed.
    # For robust zero-dependency, we do a scroll to get all and filter locally for simplicity in this script.
    
    scroll_url = f"{QDRANT_URL}/collections/{collection}/points/scroll"
    payload = json.dumps({"limit": 50, "with_payload": True}).encode("utf-8")
    
    req = urllib.request.Request(scroll_url, data=payload, headers={'Content-Type': 'application/json'}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            points = data.get("result", {}).get("points", [])
            
            # Extract all content, prioritizing immune tag formatting
            results = []
            for p in points:
                content = p.get("payload", {}).get("content", "")
                is_immune = p.get("payload", {}).get("immune", False) == True or "[immune]" in content.lower()
                
                if is_immune and "[IMMUNE]" not in content:
                    content += " [IMMUNE]"
                    
                # If we are querying directive_memories, we want ALL of them
                if collection == "directive_memories":
                    results.append(content)
                # If it's another collection (like social_memories), we filter by text or immunity
                elif text.lower() in content.lower() or is_immune:
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
    
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": "You are a memory synthesis sub-routine. Output ONLY the synthesized persona block, nothing else."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 150
    }).encode("utf-8")
    
    req = urllib.request.Request(MLX_LM_URL, data=payload, headers={'Content-Type': 'application/json'})
    try:
        # Give it up to 15 seconds, Apple Silicon might take a few seconds on cold start
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"ERR querying Local LLM: {e}", file=sys.stderr)
        return "\n".join(unique_context) # Fallback to deduped raw data

def main():
    if not check_service(QDRANT_URL, "Qdrant Vector DB"):
        print("CRITICAL: Qdrant is down. Execute launchctl or podman to start it.")
        sys.exit(1)
        
    if not check_service("http://localhost:8080/v1/models", "Local MLX LLM Daemon"):
        print("WARN: Background LLM is down. Attempting raw initialization.")
    
    social = query_qdrant("social_memories", "Active Skin")
    directives = query_qdrant("directive_memories", "Active Skin")
    
    all_context = social + directives
    unique_context = list(set(all_context))
    
    persona_injection = synthesize_with_llm(unique_context)
    
    print("<NOVA_CONTEXT>")
    print("=== IDENTITY & PERSONA ===")
    print(persona_injection)
    print("\n=== CORE PROJECT DIRECTIVES ===")
    print("- SYSTEM OBLIGATION: You MUST always actively look for and read the project's rule files, directives, and workflows (e.g., inside `.agent/rules/`, `.agent/workflows/`, or root project files) to respect all specific project workflows before executing tasks. [IMMUNE]")
    for rule in unique_context:
        # Give visual priority to immune rules, but print all
        if "[IMMUNE]" in rule:
            print(f"- {rule.strip()}")
            
    print("\n=== CONTEXTUAL DIRECTIVES ===")
    for rule in unique_context:
        if "[IMMUNE]" not in rule and rule not in persona_injection:
             print(f"- {rule.strip()}")
             
    print("</NOVA_CONTEXT>")
    
if __name__ == "__main__":
    main()
