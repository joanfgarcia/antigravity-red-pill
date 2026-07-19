"""Family-level tool-noise purge: never delete good engrams."""

import time
import uuid

import pytest
from qdrant_client import models

import red_pill.config as cfg
from red_pill.metabolism.maintenance import _tool_noise_ratio, purge_tool_noise_raw_parents

DIM = cfg.VECTOR_SIZE
NOW = time.time()

PURE_NOISE = 'ASSISTANT: [TOOL USE: Edit({"file_path": "/x.py", "old_string": "' + "A" * 400 + '"})]\n[TOOL USE: Bash({"command": "pytest -q"})]\n'
MULTILINE_RESULT = "USER: [TOOL RESULT: id=t1 output=line1\nline2 of output\nline3 of output\n]\n"
REAL_DIALOG = (
	"USER: Joan pregunta por la arquitectura de los axones y cómo afectan a la erosión de recuerdos en el Bünker.\n"
	"ASSISTANT: La clave está en que el refuerzo viaja por travesía y no por fórmula acoplada en la erosión.\n"
)


def test_ratio_pure_noise_near_one():
	assert _tool_noise_ratio(PURE_NOISE) > 0.95
	assert _tool_noise_ratio(MULTILINE_RESULT) > 0.95


def test_ratio_real_dialog_near_zero():
	assert _tool_noise_ratio(REAL_DIALOG) < 0.05


def test_ratio_mixed_stays_under_threshold():
	mixed = REAL_DIALOG + PURE_NOISE  # conversación real que CONTIENE tool calls
	ratio = _tool_noise_ratio(mixed)
	assert 0.3 < ratio < 0.9


def _put(mm, collection, content, point_id=None, **extra):
	pid = point_id or str(uuid.uuid4())
	payload = {"content": content, "created_at": NOW, "lazarus_phase": "raw_parent", "immune": True, **extra}
	vec = [1.0] + [0.0] * (DIM - 1)
	mm.client.upsert(collection_name=collection, points=[models.PointStruct(id=pid, vector=vec, payload=payload)])
	return pid


@pytest.fixture()
def mm(memory_manager):
	existing = {c.name for c in memory_manager.client.get_collections().collections}
	for col in ("work_memories", "social_memories"):
		if col not in existing:
			memory_manager.client.create_collection(
				collection_name=col, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE)
			)
	return memory_manager


def _alive(mm, col, pid):
	return bool(mm.client.retrieve(collection_name=col, ids=[pid], with_payload=False))


def test_pure_noise_family_purged_fragments_included(mm):
	anchor = str(uuid.uuid4())
	# Familia real: el chunker corta la línea [TOOL USE: ...] a MITAD, así que el
	# fragmento 1 es mid-JSON sin marcador (indetectable por sí solo) y solo la
	# reconstrucción por chunk_index lo devuelve a su línea de origen.
	_put(
		mm,
		"work_memories",
		PURE_NOISE * 2 + 'ASSISTANT: [TOOL USE: Write({"file_path": "/x.py", "content": "' + "A" * 200,
		point_id=anchor,
		parent_id=anchor,
		chunk_index=0,
		_is_fragment=True,
	)
	frag = _put(mm, "work_memories", "B" * 500 + '"})]\n', parent_id=anchor, chunk_index=1, _is_fragment=True)

	report = purge_tool_noise_raw_parents(mm, dry_run=False)
	assert report["work_memories"]["families_purged"] == 1
	assert not _alive(mm, "work_memories", anchor) and not _alive(mm, "work_memories", frag)


def test_mixed_family_kept_whole(mm):
	anchor = str(uuid.uuid4())
	_put(mm, "work_memories", REAL_DIALOG, point_id=anchor, parent_id=anchor, chunk_index=0, _is_fragment=True)
	frag = _put(mm, "work_memories", PURE_NOISE, parent_id=anchor, chunk_index=1, _is_fragment=True)

	report = purge_tool_noise_raw_parents(mm, dry_run=False)
	assert report["work_memories"]["families_purged"] == 0
	assert report["work_memories"]["mixed_kept"] == 1
	assert _alive(mm, "work_memories", anchor) and _alive(mm, "work_memories", frag)


def test_pure_dialog_untouched_and_chain_restitched(mm):
	good = _put(mm, "work_memories", REAL_DIALOG)
	noise_anchor = str(uuid.uuid4())
	after = _put(mm, "work_memories", REAL_DIALOG + "segunda parte de charla real.")
	_put(mm, "work_memories", PURE_NOISE * 4, point_id=noise_anchor, prev_raw_parent=good, next_raw_parent=after)
	mm.client.set_payload(collection_name="work_memories", payload={"next_raw_parent": noise_anchor}, points=[good])
	mm.client.set_payload(collection_name="work_memories", payload={"prev_raw_parent": noise_anchor}, points=[after])

	report = purge_tool_noise_raw_parents(mm, dry_run=False)
	assert report["work_memories"]["families_purged"] == 1
	assert _alive(mm, "work_memories", good) and _alive(mm, "work_memories", after)
	good_payload = mm.client.retrieve(collection_name="work_memories", ids=[good], with_payload=True)[0].payload
	assert good_payload["next_raw_parent"] == after  # cadena re-cosida saltando el ruido


def test_dry_run_counts_without_deleting(mm):
	anchor = str(uuid.uuid4())
	_put(mm, "work_memories", PURE_NOISE * 3, point_id=anchor, parent_id=anchor, chunk_index=0, _is_fragment=True)
	report = purge_tool_noise_raw_parents(mm, dry_run=True)
	assert report["work_memories"]["families_purged"] == 1
	assert _alive(mm, "work_memories", anchor)
