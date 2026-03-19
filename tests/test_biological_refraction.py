from unittest.mock import MagicMock

from qdrant_client.http import models

from red_pill.memory import MemoryManager


def test_biological_refraction_in_sanitize():
    """Verify that legacy monolithic engrams are correctly split into Axon-linked Twin Nodes."""
    manager = MemoryManager()
    manager.client = MagicMock()
    
    class MockPoint:
        def __init__(self, _id, content):
            self.id = _id
            self.payload = {
                "content": content,
                "reinforcement_score": 5.0,
                "immune": True,
                "color": "pink",
                "emotion": "joy",
                "intensity": 0.9
            }
            
    # Simulate an old monolithic engram
    monolithic_content = "USER: Hello World.\n\nASSISTANT: I am responding."
    legacy_point = MockPoint("legacy-123", monolithic_content)
    
    # Mock scroll to return this point once, then None indicating end
    manager.client.scroll.side_effect = [
        ([legacy_point], None)
    ]
    
    # Mock add_memory to return specific IDs for the Twin Nodes
    manager.add_memory = MagicMock(side_effect=["prompt-uuid", "response-uuid"])
    
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
