import logging
from collections import defaultdict
from typing import Dict, Optional, Tuple

import red_pill.config as cfg
from red_pill.identity import get_default_emotion, get_hedonic_set_point, update_identity
from red_pill.memory import MemoryManager

logger = logging.getLogger(__name__)

class IdentityEvaluator:
    """
    Evaluates the Evolutionary Set Point (Gravity Point) by analyzing deep memories.
    """

    @staticmethod
    def evaluate_set_point(manager: Optional[MemoryManager] = None) -> Tuple[str, str]:
        """
        Calculates the long-term personality shift by aggregating the emotional valence
        of the latest deep memories.

        Returns a tuple: (Dominant Color, Default Emotion)
        """
        if not cfg.DYNAMIC_EMOTION_SYNC:
            return get_hedonic_set_point(), get_default_emotion()

        _manager = manager if manager is not None else MemoryManager()

        # We will sample the last N memories from archive and social
        sample_limit = 100

        # Color & emotion frequencies, weighted by intensity
        color_weights: Dict[str, float] = defaultdict(float)
        emotion_weights: Dict[str, float] = defaultdict(float)

        total_memories = 0

        for collection in ["archive_memories", "social_memories"]:
            try:
                # We need payloads to read color, intensity, and emotion.
                from qdrant_client.http import models
                scroll_filter = models.Filter(must_not=[models.FieldCondition(key="immune", match=models.MatchValue(value=True))])
                points, _ = _manager.client.scroll(
                    collection_name=collection,
                    limit=sample_limit,
                    scroll_filter=scroll_filter,
                    with_payload=True,
                    with_vectors=False,
                )

                for p in points:
                    if not p.payload:
                        continue

                    color = p.payload.get("color", "gray")
                    emotion = p.payload.get("emotion", "neutral")
                    intensity = float(p.payload.get("intensity", 1.0))

                    # Weight by intensity
                    color_weights[color] += intensity
                    emotion_weights[emotion] += intensity
                    total_memories += 1

            except Exception as e:
                logger.debug(f"[EVOLUTION] Could not read {collection} for evolution: {e}")

        if total_memories == 0:
            return get_hedonic_set_point(), get_default_emotion()

        # Calculate dominant color
        dominant_color = max(color_weights.items(), key=lambda x: x[1])[0]

        # Calculate dominant emotion, excluding "neutral" if possible unless it heavily outweighs others
        # To avoid being stuck in neutral, we apply a small penalty to neutral
        if "neutral" in emotion_weights and len(emotion_weights) > 1:
            emotion_weights["neutral"] *= 0.5

        dominant_emotion = max(emotion_weights.items(), key=lambda x: x[1])[0]

        # Update persisted identity
        update_identity(dominant_color, dominant_emotion)
        logger.info(f"[EVOLUTION] Gravity Point evolved -> Color: {dominant_color.upper()}, Emotion: {dominant_emotion.upper()}")

        return dominant_color, dominant_emotion
