import pytest

from red_pill.mcp_server import handle_memorize_interaction


@pytest.mark.asyncio
async def test_silent_scribe_rejects_noise():
	# 1. Test ping (p/r)
	res = await handle_memorize_interaction({"prompt": "p", "response": "r", "role": "assistant"})
	assert "Rejected" in res[0].text

	# 2. Test ping (hello/world)
	res = await handle_memorize_interaction({"prompt": "hello", "response": "world", "role": "assistant"})
	assert "Rejected" in res[0].text

	# 3. Test interceptor loop injection
	res = await handle_memorize_interaction({"prompt": "Valid text", "response": "[INTERCEPTOR] Injected 4 context chunks", "role": "assistant"})
	assert "Rejected" in res[0].text

	# 4. Test Orchestrator log noise
	res = await handle_memorize_interaction({"prompt": "Status", "response": "ORCHESTRATOR: Swarm Task Complete", "role": "assistant"})
	assert "Rejected" in res[0].text

	# 5. Test Non-Operator Roles
	res = await handle_memorize_interaction({"prompt": "Audit log", "response": "Done", "role": "smith"})
	assert "Rejected" in res[0].text


@pytest.mark.asyncio
async def test_silent_scribe_accepts_valid_interaction():
	res = await handle_memorize_interaction({"prompt": "Who are you?", "response": "I am Aleth.", "role": "assistant"})
	assert "Engram queue registration initiated" in res[0].text
