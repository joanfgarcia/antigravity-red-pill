import logging
import os
import sys

# Project root setup
sys.path.append(os.getcwd() + "/src")

# Environment setup (Test values)
os.environ["LAZARUS_SYNC_ENABLED"] = "True"
os.environ["LAZARUS_STATE_FILE"] = "/tmp/lazarus_test_state.json"

from red_pill.swarm.lazarus import LamportClock, LazarusSync

logging.basicConfig(level=logging.INFO)

def test_lamport_clock():
    print("--- Testing Lamport Clock (Phase 6.1) ---")

    # Cleanup previous state
    if os.path.exists("/tmp/lazarus_test_state.json"):
        os.remove("/tmp/lazarus_test_state.json")

    # 1. Local Ticking
    aleph_clock = LamportClock("Aleph")
    t1 = aleph_clock.tick()
    t2 = aleph_clock.tick()
    print(f"Aleph Ticks: {t1} -> {t2}")
    assert t2 == t1 + 1

    # 2. Persistence Check
    # Create a new instance for the same agent
    aleph_new = LamportClock("Aleph")
    t3 = aleph_new.tick()
    print(f"Aleph Persistent Tick: {t3}")
    assert t3 == t2 + 1

    # 3. Synchronization (Causal Ordering)
    # Nova receives a message from Aleph at t3
    nova_clock = LamportClock("Nova")
    t_nova_init = nova_clock.counter
    print(f"Nova Init Clock: {t_nova_init}")

    nova_clock.update(t3)
    t_nova_sync = nova_clock.counter
    print(f"Nova Sync Clock (after sync with Aleph @ {t3}): {t_nova_sync}")

    # Nova's clock must be greater than Aleph's
    assert t_nova_sync > t3
    assert t_nova_sync == t3 + 1

    print("SUCCESS: Lamport Clock logic verified.")
    return True

def test_lazarus_packaging():
    print("--- Testing Lazarus Engram Packaging ---")

    sync = LazarusSync("canonical", "Sam")
    engram = sync.prepare_engram("Knowledge is power.", [0.5]*384, {"topic": "cybernetics"})

    print(f"Packaged Engram Metadata: {engram['metadata']}")
    assert "lamport_ts" in engram["metadata"]
    assert engram["metadata"]["source_agent"] == "Sam"
    assert engram["metadata"]["lamport_ts"] > 0

    print("SUCCESS: Lazarus packaging verified.")
    return True

if __name__ == "__main__":
    try:
        if test_lamport_clock() and test_lazarus_packaging():
            print("\n--- ALL LAZARUS CORE TESTS PASSED ---")
            sys.exit(0)
        else:
            print("\n--- TEST FAILURE ---")
            sys.exit(1)
    except Exception as e:
        print(f"\n--- ERROR DURING TEST: {e} ---")
        sys.exit(1)
