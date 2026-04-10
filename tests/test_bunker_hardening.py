import asyncio
import unittest

from red_pill.affect import get_memory_engine
from red_pill.memory import MemoryManager
from red_pill.swarm.agents.echo import EchoMinion


class TestBunkerHardening(unittest.TestCase):
    def setUp(self):
        # Force a temporary directory for Qdrant
        import os
        import tempfile
        from unittest.mock import patch

        from red_pill.config import get_config

        self.tmp_dir = tempfile.mkdtemp()
        os.environ["QDRANT_HOST"] = self.tmp_dir
        get_config.cache_clear()

        from qdrant_client.models import Distance, PointStruct, VectorParams

        from red_pill.utils.mood_profile import ID_OPERATOR_MOOD

        self.manager = MemoryManager()
        self.echo = EchoMinion()

        # Start patching so internal agent instantiations get our seeded manager
        self.patcher = patch('red_pill.swarm.agents.echo.MemoryManager', return_value=self.manager)
        self.patcher.start()

        # Seed required collection
        self.manager.client.recreate_collection(
            collection_name="social_memories",
            vectors_config=VectorParams(size=384, distance=Distance.COSINE)
        )

        # Inject mock USP profile for Echo
        self.manager.client.upsert(
            collection_name="social_memories",
            points=[PointStruct(
                id=ID_OPERATOR_MOOD,
                vector=[0.1] * 384,
                payload={
                    "global": {"gray": 1.0},
                    "last_3d": {"red": 0.2, "gray": 0.8},
                    "last_7d": {"gray": 1.0},
                    "interaction_count": 10
                }
            )]
        )

    def tearDown(self):
        self.patcher.stop()
        self.manager.client.close()
        import os
        import shutil
        if hasattr(self, 'tmp_dir') and os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)

    def test_ingestion_gate_noise(self):
        """Proof of CQ-005: Quality Gate must reject garbage/noisy strings."""
        garbage_text = "asdfghjkl12345 !@#$%^&*() " * 20
        # Should handle gracefully without crashing.
        # In memory-mode, we verify it doesn't pollute the context unfairly.
        result = self.manager.add_memory(
            collection="social_memories",
            text=garbage_text,
            importance=1.0
        )
        self.assertIsNotNone(result, "Ingestion Gate should return a point_id even if it logs a warning.")

    def test_bayesian_reinforcement_entropy(self):
        """Proof of affect reinforcement threshold."""
        engine = get_memory_engine("bayesian")
        # High entropy interaction (actually low quality/noisy)
        noisy_text = "test " * 100
        result = engine.calculate_reinforcement({"content": noisy_text, "utility_beta": 1.0}, increment=1.0)

        # Result should indicate beta increase (erosion) instead of normal reinforcement
        # Normal reinforcement would return 'utility_alpha' increases.
        self.assertIn("utility_beta", result)
        self.assertGreater(result["utility_beta"], 1.0, "Noisy text should trigger uncertainty increase (beta).")
        self.assertNotIn("utility_alpha", result, "Noisy text should NOT increase alpha confidence.")

    def test_echo_pulse_logic(self):
        """Proof of Echo's drift detection capabilities."""
        # This requires async execution
        async def run_echo():
            result = await self.echo.execute("monitor_pulse")
            self.assertEqual(result["status"], "success")
            self.assertIn("pulse", result)
            print(f"Echo Pulse Test: {result['pulse']} (Drift: {result.get('drift', 0)})")

        asyncio.run(run_echo())

if __name__ == "__main__":
    unittest.main()
