"""Surgical compaction of mixed families + murky-pointer detection (self-evocation)."""

import time
import uuid

import pytest
from qdrant_client import models

import red_pill.config as cfg
from red_pill.metabolism.maintenance import _is_murky_pointer, compact_tool_noise, rewrite_tool_noise_families

DIM = cfg.VECTOR_SIZE
NOW = time.time() - 86400  # ayer: verificamos que created_at se preserva

DIALOG_1 = "USER: revisa el weaver y dime si la puerta 0.5 teje bien los pares de la misma sesión."
DIALOG_2 = "ASSISTANT: La puerta 0.5 teje los pares correctos; el ruido queda por debajo de 0.41."
NOISE_LINE = 'ASSISTANT: [TOOL USE: Edit({"file_path": "/home/joan/axons.py", "old_string": "' + "A" * 600 + '"})]'
RESULT_BLOCK = "USER: [TOOL RESULT: id=t9 output=8 passed in 1.52s\n" + "ruido de log " * 200 + "]"
MIXED = f"{DIALOG_1}\n{NOISE_LINE}\n{RESULT_BLOCK}\n{DIALOG_2}\n"


def test_compact_preserves_dialog_byte_exact():
	compacted = compact_tool_noise(MIXED)
	assert DIALOG_1 in compacted and DIALOG_2 in compacted
	assert len(compacted) < len(MIXED) * 0.4


def test_compact_markers_are_self_evocative():
	compacted = compact_tool_noise(MIXED)
	assert "[TOOL: Edit file_path=/home/joan/axons.py]" in compacted  # qué y sobre qué
	assert "8 passed in 1.52s" in compacted  # la cabeza del resultado (el veredicto)
	assert "ruido de log" * 3 not in compacted


def test_compact_noop_on_pure_dialog():
	text = DIALOG_1 + "\n" + DIALOG_2
	assert compact_tool_noise(text) == text


def test_murky_pointer_detection():
	assert _is_murky_pointer("file:///home/joan/.gemini/antigravity/brain/94f46277/scratch/x.py") is True
	assert _is_murky_pointer("claude_code_5f421027-fea6-4779-b745-ba7eef01ba34") is True
	assert _is_murky_pointer("Taller de destilación: el guion vive en scratch/distill_workshop.py y prueba prompts V3") is False
	assert _is_murky_pointer(DIALOG_1) is False


@pytest.fixture()
def mm(memory_manager):
	existing = {c.name for c in memory_manager.client.get_collections().collections}
	for col in ("work_memories", "social_memories"):
		if col not in existing:
			memory_manager.client.create_collection(
				collection_name=col, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE)
			)
	return memory_manager


def _put(mm, collection, content, point_id=None, **extra):
	pid = point_id or str(uuid.uuid4())
	payload = {"content": content, "created_at": NOW, "lazarus_phase": "raw_parent", "immune": True, **extra}
	vec = [1.0] + [0.0] * (DIM - 1)
	mm.client.upsert(collection_name=collection, points=[models.PointStruct(id=pid, vector=vec, payload=payload)])
	return pid


def test_rewrite_preserves_identity_chain_and_time(mm, monkeypatch):
	monkeypatch.setattr(mm, "_get_vector", lambda text: [1.0] + [0.0] * (DIM - 1))
	prev = _put(mm, "work_memories", DIALOG_1)
	anchor = str(uuid.uuid4())
	_put(
		mm,
		"work_memories",
		MIXED * 2,
		point_id=anchor,
		parent_id=anchor,
		chunk_index=0,
		_is_fragment=True,
		prev_raw_parent=prev,
		source_buffer_id="claude_code_test",
	)
	frag = _put(mm, "work_memories", NOISE_LINE + "\n", parent_id=anchor, chunk_index=1, _is_fragment=True)

	report = rewrite_tool_noise_families(mm, dry_run=False)
	assert report["work_memories"]["families_rewritten"] == 1

	payload = mm.client.retrieve(collection_name="work_memories", ids=[anchor], with_payload=True)[0].payload
	assert DIALOG_1 in payload["content"] and "[TOOL: Edit" in payload["content"]
	assert payload["created_at"] == NOW  # el tiempo original sobrevive
	assert payload["prev_raw_parent"] == prev  # la cadena sobrevive
	assert payload["source_buffer_id"] == "claude_code_test"
	assert payload["immune"] is True
	assert payload["rewritten_from"] == "tool_noise_compaction"
	assert not mm.client.retrieve(collection_name="work_memories", ids=[frag], with_payload=False)  # metralla vieja fuera


def test_rewrite_skips_low_noise_families(mm, monkeypatch):
	monkeypatch.setattr(mm, "_get_vector", lambda text: [1.0] + [0.0] * (DIM - 1))
	pid = _put(mm, "work_memories", DIALOG_1 + "\n" + DIALOG_2)
	report = rewrite_tool_noise_families(mm, dry_run=False)
	assert report["work_memories"]["families_rewritten"] == 0
	payload = mm.client.retrieve(collection_name="work_memories", ids=[pid], with_payload=True)[0].payload
	assert payload["content"] == DIALOG_1 + "\n" + DIALOG_2


def test_rewrite_dry_run_touches_nothing(mm, monkeypatch):
	monkeypatch.setattr(mm, "_get_vector", lambda text: [1.0] + [0.0] * (DIM - 1))
	anchor = str(uuid.uuid4())
	_put(mm, "work_memories", MIXED * 2, point_id=anchor, parent_id=anchor, chunk_index=0, _is_fragment=True)
	report = rewrite_tool_noise_families(mm, dry_run=True)
	assert report["work_memories"]["families_rewritten"] == 1
	payload = mm.client.retrieve(collection_name="work_memories", ids=[anchor], with_payload=True)[0].payload
	assert "rewritten_from" not in payload
