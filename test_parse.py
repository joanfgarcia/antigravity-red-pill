import json

payload_str = '{"text": "{\\"command\\": \\"LIST_CASCADES\\", \\"mode\\": \\"conversational\\", \\"_t\\": 1778626495.1705127}", "sender_id": "671868686", "mode": "conversational"}'
first_payload = json.loads(payload_str)
command = first_payload.get("command")

if not command and "text" in first_payload:
    try:
        nested = json.loads(first_payload["text"])
        if isinstance(nested, dict) and "command" in nested:
            command = nested["command"]
            first_payload = nested
    except Exception as e:
        print(f"Error: {e}")

print(f"Command: {command}")
