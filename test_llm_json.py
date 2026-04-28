import json
import urllib.request

payload = json.dumps(
	{
		"messages": [
			{
				"role": "system",
				"content": 'You are an Amygdala-driven consolidation engine. You must ONLY output a valid JSON object. Examples of keys: \'summary\', \'emotion\', \'intensity\'. Example output: {"summary": "Session overview", "emotion": "neutral", "intensity": 0.5}',
			},
			{"role": "user", "content": "Analyze this text and return ONLY JSON:\nHello there, I feel great about the new architecture."},
		],
		"max_tokens": 150,
		"temperature": 0.1,
		"stop": ["<|im_end|>", "<|eot_id|>", "<|endoftext|>", "user:", "assistant:", "```"],
	}
)
req = urllib.request.Request("http://127.0.0.1:8760/v1/chat/completions", data=payload.encode(), headers={"Content-Type": "application/json"})
try:
	with urllib.request.urlopen(req) as resp:
		print(json.loads(resp.read().decode())["choices"][0]["message"]["content"])
except Exception as e:
	print(f"Error: {e}")
