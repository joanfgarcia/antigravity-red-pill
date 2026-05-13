import json
import sqlite3

conn = sqlite3.connect('/home/joan/.local/share/neon-link/events.db')
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT payload FROM inbox WHERE id = 57").fetchone()
payload_str = row["payload"]
print("PAYLOAD STR:", repr(payload_str))
first_payload = json.loads(payload_str)
command = first_payload.get("command")
print("FIRST COMMAND:", command)

if not command and "text" in first_payload:
    try:
        nested = json.loads(first_payload["text"])
        if isinstance(nested, dict) and "command" in nested:
            command = nested["command"]
            first_payload = nested
    except Exception as e:
        print("EXCEPTION:", e)

print("FINAL COMMAND:", command)
print("FINAL PAYLOAD:", first_payload)
