
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from qdrant_client.http import models

import red_pill.config as cfg
from red_pill.memory import MemoryManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AgentSmith")

import pytest

@pytest.mark.integration
def attack_clone_army(manager, target_id, iterations=100):
    """
    Simulates high-concurrency reinforcement attacks on a single engram.
    Goal: Expose race conditions where reinforcing simultaneous threads
    overwrite each other's score increments.
    """
    logger.info(f"[ATTACK] The Clone Army: Launching {iterations} concurrent reinforcements on {target_id}...")

    def reinforce_task():
        try:
            manager._reinforce_points("stress_test", [target_id], {target_id: 0.1})
        except Exception as e:
            logger.error(f"Clone died: {e}")

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(reinforce_task) for _ in range(iterations)]
        for f in futures:
            f.result()

    # Check final score
    points = manager.client.retrieve("stress_test", ids=[target_id], with_payload=True)
    final_score = points[0].payload["reinforcement_score"]
    expected_score = 1.0 + (0.1 * iterations)

    logger.info(f"[RESULT] Clone Army: Final Score {final_score:.2f} / Expected {expected_score:.2f}")
    if final_score < expected_score * 0.9: # Allow small float error but not massive loss
        msg = f"Race condition detected! Lost {(expected_score - final_score):.2f} points."
        logger.error(f"[FAIL] {msg}")
        pytest.fail(msg)
    else:
        logger.info("[SUCCESS] System withstood the clone attack.")

def attack_poison_pill(manager):
    """
    Injects malformed payloads and diverse data types into metadata.
    Goal: Corrupt the memory schema or cause crashes during retrieval.
    """
    logger.info("[ATTACK] Poison Pill: Injecting toxic data types...")

    poison_data = [
        {"complex": {"nested": [1, 2, {"deep": "value"}]}}, # Deep nesting
        {"huge_string": "A" * 10000}, # Buffer overflow attempt
        {"null_byte": "user\x00data"}, # C-string terminator injection
        {"sql_injection": "'; DROP TABLE memories; --"}, # Classic SQL (useless on Qdrant but checks handling)
        {"unicode_chaos": "﷽ ⚠️ 🤡 ΰ α"} # Unicode stress
    ]

    ids = []
    rejected_count = 0
    for i, meta in enumerate(poison_data):
        try:
            pid = manager.add_memory("stress_test", f"Poison {i}", metadata=meta)
            ids.append(pid)
            logger.error(f"[FAIL] Injection {i} accepted! Schema validation failed.")
        except Exception as e:
            # We expect validation errors here
            logger.info(f"[SUCCESS] Injection {i} rejected: {e}")
            rejected_count += 1

    if rejected_count == len(poison_data):
        logger.info("[SUCCESS] All poison pills rejected by Ontological Shield.")
    else:
        logger.warning(f"[FAIL] Only {rejected_count}/{len(poison_data)} poison pills blocked.")

    # Only attempt retrieval if any got through (which shouldn't happen)
    if ids:
        logger.info(f"[INFO] Injected {len(ids)} poison pills. Attempting retrieval...")
        try:
            results = manager.search_and_reinforce("stress_test", "Poison")
            logger.info(f"[SUCCESS] Retrieved {len(results)} poison pills without crashing.")
            for res in results:
                pass # just iterating to ensure no deserialization error
        except Exception as e:
            logger.error(f"[CRITICAL] System crashed on poison pill retrieval: {e}")

def attack_erosion_flood(manager, target_id):
    """
    Floods the system with erosion cycles while reading.
    Goal: Test locking and data consistency during mass updates.
    """
    logger.info("[ATTACK] Erosion Flood: Initiating rapid decay cycles...")

    stop_event = threading.Event()

    def erosion_loop():
        while not stop_event.is_set():
            manager.apply_erosion("stress_test", rate=0.01)
            time.sleep(0.01)

    def read_loop():
        reads = 0
        while not stop_event.is_set():
            manager.client.retrieve("stress_test", ids=[target_id], with_payload=True)
            reads += 1
            if reads % 50 == 0:
                time.sleep(0.1)

    erosion_thread = threading.Thread(target=erosion_loop)
    read_thread = threading.Thread(target=read_loop)

    erosion_thread.start()
    read_thread.start()

    time.sleep(3) # Let it burn for 3 seconds
    stop_event.set()

    erosion_thread.join()
    read_thread.join()
    logger.info("[SUCCESS] Erosion Flood sustained without deadlock.")

def main():
    logger.info("--- AGENT SMITH INITIALIZED ---")

    # Setup
    manager = MemoryManager()
    # manager.client.recreate_collection is deprecated in modern clients
    # using delete + create pattern
    collection_name = "stress_test"
    manager.client.delete_collection(collection_name)
    manager.client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=cfg.VECTOR_SIZE, distance=models.Distance.COSINE)
    )

    # 1. Concurrency
    target = manager.add_memory("stress_test", "Neo is the One")
    attack_clone_army(manager, target)

    # 2. Injection
    attack_poison_pill(manager)

    # 3. Erosion Load
    attack_erosion_flood(manager, target)

    logger.info("--- STRESS TEST COMPLETE ---")

if __name__ == "__main__":
    main()
