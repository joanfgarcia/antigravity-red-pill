from unittest.mock import MagicMock

from red_pill.memory import MemoryManager


def test_biological_refraction_in_sanitize():
	"""Verify that legacy monolithic engrams are correctly split into Axon-linked Twin Nodes."""
	manager = MemoryManager()
	manager.client = MagicMock()

	class MockPoint:
		def __init__(self, _id, content):
			self.id = _id
			self.payload = {"content": content, "reinforcement_score": 5.0, "immune": True, "color": "pink", "emotion": "joy", "intensity": 0.9}

	# Simulate an old monolithic engram
	monolithic_content = "USER: Hello World.\n\nASSISTANT: I am responding."
	legacy_point = MockPoint("legacy-123", monolithic_content)

	# Mock scroll to return this point once, then None indicating end
	manager.client.scroll.side_effect = [([legacy_point], None)]

	# Mock add_memory to return specific IDs for the Twin Nodes
	manager.add_memory = MagicMock(side_effect=["prompt-uuid", "response-uuid"])  # type: ignore

	# Execute sanitize
	res = manager.sanitize("work_memories", dry_run=False, strict=False)

	# Assertions
	# 1. Monolithic point was deleted
	manager.client.delete.assert_called_once()
	assert manager.client.delete.call_args[1]["points_selector"].points == ["legacy-123"]

	# 2. add_memory was called twice with correct decoupled texts
	assert manager.add_memory.call_count == 2
	calls = manager.add_memory.call_args_list
	assert calls[0][0][1] == "Operator Prompt: Hello World."
	assert calls[1][0][1] == "AI Response Node: I am responding."

	# Check attributes preserved
	assert calls[0][1]["force_immune"] is True
	assert calls[0][1]["color"] == "pink"

	# 3. Axon topological link was created
	manager.client.set_payload.assert_called_once()
	assert manager.client.set_payload.call_args[1]["payload"] == {"associations": ["prompt-uuid"]}
	assert manager.client.set_payload.call_args[1]["points"] == ["response-uuid"]

	# 4. Correct refraction stats reported
	assert res["refracted_records"] == 1


def test_sanitize_skips_structural_material():
	"""Regresión 2026-09-14: la refracción NO debe tocar el ecosistema del sueño
	(hubs, raw_parents, sequence_chunks, fragmentos) — solo dedup aplica ahí."""
	manager = MemoryManager()
	manager.client = MagicMock()

	class MockPoint:
		def __init__(self, _id, content, lazarus=None, is_fragment=False):
			self.id = _id
			self.payload = {"content": content, "lazarus_phase": lazarus, "_is_fragment": is_fragment}

	hub = MockPoint("hub-1", "x" * 2000, lazarus="synthesis_hub")
	raw = MockPoint("raw-1", "y" * 1200, lazarus="raw_parent")
	frag = MockPoint("frag-1", "z" * 900, is_fragment=True)
	manager.client.scroll.side_effect = [([hub, raw, frag], None)]
	manager.add_memory = MagicMock()

	res = manager.sanitize("work_memories", dry_run=False, strict=False)
	assert res["refracted_records"] == 0
	manager.client.delete.assert_not_called()
	manager.add_memory.assert_not_called()


def test_sanitize_skips_oversized_normal_non_legacy():
	"""Regresión 2026-09-14: un 'normal' legítimo largo (> CHUNK_THRESHOLD) que NO
	es legacy NO debe re-fragmentarse (se convertiría en _is_fragment, excluido del recall)."""
	manager = MemoryManager()
	manager.client = MagicMock()

	class MockPoint:
		def __init__(self, _id, content, lazarus=None, is_fragment=False):
			self.id = _id
			self.payload = {"content": content, "lazarus_phase": lazarus, "_is_fragment": is_fragment}

	normal_largo = MockPoint("n-1", "texto curado legítimo " + "x" * 2000)  # sin prefijo legacy
	manager.client.scroll.side_effect = [([normal_largo], None)]
	manager.add_memory = MagicMock()

	res = manager.sanitize("work_memories", dry_run=False, strict=False)
	assert res["refracted_records"] == 0
	manager.client.delete.assert_not_called()
	manager.add_memory.assert_not_called()


def test_sanitize_still_refracts_oversized_legacy():
	"""El Fragmentation Guard SÍ aplica a legacy políglota largo (USER:/ASSISTANT:)."""
	manager = MemoryManager()
	manager.client = MagicMock()

	class MockPoint:
		def __init__(self, _id, content, lazarus=None, is_fragment=False):
			self.id = _id
			self.payload = {"content": content, "lazarus_phase": lazarus, "_is_fragment": is_fragment}

	legacy_largo = MockPoint("l-1", "USER: " + "m" * 1500)
	manager.client.scroll.side_effect = [([legacy_largo], None)]
	manager.add_memory = MagicMock(return_value="new-id")

	res = manager.sanitize("work_memories", dry_run=False, strict=False)
	assert res["refracted_records"] == 1
	manager.client.delete.assert_called_once()
