"""
Sleep-side hub erosion (erode_work_hubs) — filter and threshold coherence.

Two defects fixed together with the P0 recall fix:
1. The scroll filter queried "metadata.lazarus_phase" but the field is stored at
   the payload top level — it matched 0 points, so hub erosion NEVER ran.
2. The deletion threshold was a hardcoded 0.3, incoherent with the Bayesian
   engine's calibrated 0.2. It now reads the engine's deletion_threshold.
"""

import time

from qdrant_client.http import models

from red_pill.affect import BayesianEngine
from red_pill.memory import MemoryManager
from red_pill.metabolism.maintenance import erode_work_hubs

_STALE_ID = "00000000-0000-0000-0000-00000000aa01"
_DOOMED_ID = "00000000-0000-0000-0000-00000000aa02"
_FRESH_ID = "00000000-0000-0000-0000-00000000aa03"
_IMMUNE_ID = "00000000-0000-0000-0000-00000000aa04"

DAY = 86400.0


def _hub(content, last_recalled_at, alpha=1.0, beta=1.0, immune=False):
	return {
		"content": content,
		"lazarus_phase": "synthesis_hub",  # top-level, as add_memory stores it
		"utility_alpha": alpha,
		"utility_beta": beta,
		"reinforcement_score": alpha / (alpha + beta),
		"intensity": 0.5,
		"immune": immune,
		"created_at": last_recalled_at,
		"last_recalled_at": last_recalled_at,
		"color": "gray",
		"emotion": "neutral",
		"importance": 1.0,
	}


def _seed(mm: MemoryManager):
	mm._ensure_collection("work_memories")
	now = time.time()
	points = [
		# Stale (1 day unrecalled) but healthy prior: must erode, not die.
		models.PointStruct(id=_STALE_ID, vector=[0.1] * 384, payload=_hub("stale hub", now - DAY)),
		# Stale and already deeply uncertain: beta+0.5 pushes utility <= threshold -> deleted.
		models.PointStruct(id=_DOOMED_ID, vector=[0.1] * 384, payload=_hub("doomed hub", now - DAY, beta=3.7)),
		# Recalled just now: untouched.
		models.PointStruct(id=_FRESH_ID, vector=[0.1] * 384, payload=_hub("fresh hub", now)),
		# Immune: untouched even when stale and uncertain.
		models.PointStruct(id=_IMMUNE_ID, vector=[0.1] * 384, payload=_hub("immune hub", now - DAY, beta=9.0, immune=True)),
	]
	mm.client.upsert(collection_name="work_memories", points=points)


def _get(mm, pid):
	pts = mm.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=True)
	return pts[0].payload if pts else None


def test_erosion_actually_matches_hubs(memory_manager):
	"""Regression: the filter must match top-level lazarus_phase (the nested
	metadata.lazarus_phase key matched 0 points and erosion was a silent no-op)."""
	_seed(memory_manager)
	erode_work_hubs(memory_manager)

	stale = _get(memory_manager, _STALE_ID)
	assert stale is not None
	assert stale["utility_beta"] == 1.5, "stale hub must have been touched by erosion (beta 1.0 -> 1.5)"


def test_stale_healthy_hub_erodes_but_survives(memory_manager):
	_seed(memory_manager)
	erode_work_hubs(memory_manager)

	stale = _get(memory_manager, _STALE_ID)
	assert stale is not None, "utility 1/(1+1.5)=0.4 > threshold: must survive"
	assert stale["reinforcement_score"] == 0.4
	assert stale["intensity"] == 0.425


def test_deeply_uncertain_hub_is_deleted(memory_manager):
	_seed(memory_manager)
	erode_work_hubs(memory_manager)

	assert _get(memory_manager, _DOOMED_ID) is None, "utility 1/(1+4.2)~=0.192 <= threshold: must be forgotten"


def test_fresh_hub_untouched(memory_manager):
	_seed(memory_manager)
	erode_work_hubs(memory_manager)

	fresh = _get(memory_manager, _FRESH_ID)
	assert fresh is not None
	assert fresh["utility_beta"] == 1.0, "recently recalled hub must not erode"


def test_immune_hub_untouched(memory_manager):
	_seed(memory_manager)
	erode_work_hubs(memory_manager)

	immune = _get(memory_manager, _IMMUNE_ID)
	assert immune is not None, "immune hubs are never forgotten"
	assert immune["utility_beta"] == 9.0


def test_threshold_is_the_engines(memory_manager):
	"""Coherence: sleep-side deletion uses the Bayesian engine's calibrated
	threshold (0.2), not a divergent hardcoded value."""
	assert BayesianEngine().deletion_threshold == 0.2
	# A hub whose post-erosion utility lands between 0.2 and the old 0.3
	# (1/(1+2.8+0.5) ~= 0.233) must now SURVIVE.
	now = time.time()
	memory_manager._ensure_collection("work_memories")
	pid = "00000000-0000-0000-0000-00000000aa05"
	memory_manager.client.upsert(
		collection_name="work_memories",
		points=[models.PointStruct(id=pid, vector=[0.1] * 384, payload=_hub("borderline hub", now - DAY, beta=2.8))],
	)
	erode_work_hubs(memory_manager)
	assert _get(memory_manager, pid) is not None, "utility ~0.233 > 0.2: must survive under the calibrated threshold"
