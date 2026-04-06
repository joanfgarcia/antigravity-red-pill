import json
import urllib.request

payload = json.dumps({
    "messages": [{"role": "user", "content": "Hello, what is your name?"}],
    "max_tokens": 50,
    "temperature": 0.1,
    "stop": ["<|eot_id|>"]
})
req = urllib.request.Request("http://127.0.0.1:8760/v1/chat/completions", data=payload.encode(), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    print(json.loads(resp.read().decode())['choices'][0]['message']['content'])
