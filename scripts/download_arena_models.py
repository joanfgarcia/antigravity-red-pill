import json
import os
import urllib.request


def get_file(repo):
	url = f"https://huggingface.co/api/models/{repo}/tree/main"
	req = urllib.request.Request(url)
	try:
		with urllib.request.urlopen(req) as response:
			files = json.loads(response.read().decode())
			for f in files:
				if "q4_k_m" in f["path"].lower():
					path = f["path"]
					return f"https://huggingface.co/{repo}/resolve/main/{path}"
	except Exception as e:
		print("Error fetching:", repo, e)
	return None


urls = [
	get_file("bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF"),
	get_file("Qwen/Qwen2.5-7B-Instruct-GGUF"),
	get_file("ChiKoi7/Falcon3-3B-Instruct-Heretic-GGUF"),
]

WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.path.expanduser("~/Documents/IA"))
MODELS_DIR = os.path.join(WORKSPACE_ROOT, "sharing", "models", "gguf")

os.makedirs(MODELS_DIR, exist_ok=True)
for url in urls:
	if url:
		print(f"Downloading {url}...")
		os.system(f"wget -b -q -c {url} -P {MODELS_DIR}")
		print("Download started in background.")
