import os
import sys
import logging

# Project root setup
sys.path.append(os.getcwd() + "/src")

# Environment setup
os.environ["MILVUS_ENABLED"] = "True"
os.environ["MILVUS_LITE_ENABLED"] = "True"
os.environ["MILVUS_LITE_PATH"] = "/tmp/resonance_test.db"
os.environ["RESONANCE_THRESHOLD"] = "0.5"

import red_pill.config as cfg
from red_pill.swarm.resonance import ResonanceObserver
from red_pill.hive import HiveMind
from pymilvus import Collection, utility

logging.basicConfig(level=logging.INFO)

def test_semantic_resonance():
    print("--- Testing Semantic Resonance (Phase 7) ---")
    
    agent_id = "Nova@Joan"
    other_agent = "Aleph@External"
    collection = "work_memories"
    
    # 0. Cleanup
    if os.path.exists("/tmp/resonance_test.db"):
        os.remove("/tmp/resonance_test.db")

    hive = HiveMind()
    observer = ResonanceObserver(agent_id)

    # 1. Insert an "Interesting" engram from another agent
    # Topic: Quantum computing in the swarm
    topic_vector = [0.2] * cfg.VECTOR_SIZE
    hive.transmit_experience(
        collection,
        "Breakthrough: Quantum nodes successfully integrated into swarm v4.0.",
        topic_vector,
        metadata={"agent_id": other_agent, "importance": 9.0}
    )
    print("Mock intelligence inserted into Hive by another agent.")

    # 2. Check Resonance with a close Hub Vector
    hub_vector = [0.21] * cfg.VECTOR_SIZE # Close to 0.2
    print(f"Nova is scanning the Hive for resonance with focus: {hub_vector[0]}...")
    
    matches = observer.check_resonance(hub_vector, collection)
    
    print(f"Found {len(matches)} resonating engrams.")
    assert len(matches) > 0
    assert "Quantum nodes" in matches[0]["content"]

    # 3. Verify Trigger Execution
    print("Executing trigger for top match...")
    observer.trigger_reaction(matches[0])
    
    # 4. Filter Check (Self-Resonance)
    # Insert an engram from Nova herself
    hive.transmit_experience(
        collection,
        "Nova's own research on quantum gates.",
        topic_vector,
        metadata={"agent_id": agent_id, "importance": 8.0}
    )
    
    # Nova searches again. She should NOT react to her own research (to avoid loops).
    matches_self_test = observer.check_resonance(hub_vector, collection)
    # The first one should still be the Aleph one, but Nova's one should be filtered in the observer logic.
    print(f"Resonance matches after self-post: {len(matches_self_test)}")
    for m in matches_self_test:
        assert m.get("source_agent") != agent_id

    return True

if __name__ == "__main__":
    try:
        if test_semantic_resonance():
            print("\n--- SEMANTIC RESONANCE TESTS PASSED ---")
            sys.exit(0)
        else:
            print("\n--- TEST FAILURE ---")
            sys.exit(1)
    except Exception as e:
        print(f"\n--- ERROR DURING TEST: {e} ---")
        sys.exit(1)
