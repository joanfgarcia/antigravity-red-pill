"""NB-001 · F1 — endurecer la escritura de la textura del hub.

El ajuste por defecto ya existe (`synthesize_hub_v2` parte la textura en
`texture_parts` desde `e6188b7`); esta fase es el ENDURECIMIENTO para
synthesizers custom que devuelven una textura sin `texture_parts` que excede
`MAX_METADATA_STR`, más el hueco real de `jobs/drivers/distill.py` (que
descartaba `texture_parts`).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from red_pill.metabolism.hub_synthesis import _synthesize_one


def _memory() -> MagicMock:
	"""Fake memory_manager: sin idempotencia previa, escritura aceptada."""
	memory = MagicMock()
	memory.client.retrieve.return_value = []
	memory.add_memory.return_value = "hub1"
	memory.client.scroll.return_value = ([], None)
	return memory


def _members() -> list:
	return [("m1", {"content": "x", "session_id": "s", "created_at": 1.0})]


def _write_hub(monkeypatch, synth) -> dict:
	"""Ejecuta `_synthesize_one` con un synthesizer falso y devuelve la metadata."""
	import red_pill.config as cfg

	memory = _memory()
	# Hermético a un `.env` que desactivase el scrub: el contrato lo exige ON.
	monkeypatch.setattr(cfg, "SW_HUB_SCRUB_ENABLED", True, raising=False)
	result = _synthesize_one(
		memory, "work_memories", "s", _members(), synth, lambda c: ("neutral", 0.5), force=True
	)
	assert result == "written"
	return memory.add_memory.call_args.kwargs["metadata"]


def test_oversized_texture_without_parts_is_split_before_write(monkeypatch):
	"""P2.1: textura de 3.000 chars sin `texture_parts` → hub con partes y textura vacía."""
	texture = "x" * 3000

	def synth(chunks, cache_namespace=None):
		return {"title": "T", "summary": "S", "texture": texture, "lang": "es"}

	metadata = _write_hub(monkeypatch, synth)

	assert "texture" not in metadata
	parts = metadata["texture_parts"]
	assert parts and all(len(p) <= 1024 for p in parts)
	assert "".join(parts) == texture  # lossless: no se pierde un carácter
	assert metadata["hub_texture_split"] is True
	assert metadata["hub_texture_split_fallback"] is True


def test_oversized_texture_secret_is_redacted_in_parts(monkeypatch):
	"""P2.2: scrub antes de partir y en cada parte — el secreto no sobrevive."""
	secret = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
	texture = ("atmosfera " * 300) + " " + secret

	def synth(chunks, cache_namespace=None):
		return {"title": "T", "summary": "S", "texture": texture, "lang": "es"}

	metadata = _write_hub(monkeypatch, synth)

	combined = "".join(metadata["texture_parts"])
	assert secret not in combined
	assert "[SECRET_REDACTED]" in combined


def test_texture_within_limit_is_not_split(monkeypatch):
	"""Guard no toca texturas que caben (sin partición espuria)."""
	texture = "atmósfera serena"

	def synth(chunks, cache_namespace=None):
		return {"title": "T", "summary": "S", "texture": texture, "lang": "es"}

	metadata = _write_hub(monkeypatch, synth)

	assert metadata["texture"] == texture
	assert "texture_parts" not in metadata


def test_distill_driver_forwards_texture_parts(monkeypatch):
	"""P2.3: jobs/drivers/distill.py propaga `texture_parts` al payload (antes se descartaba)."""
	import red_pill.jobs.drivers.distill as d

	fake_mm = MagicMock()
	fake_client = fake_mm.client
	fake_client.collection_exists.return_value = True
	point = MagicMock()
	point.id = "p1"
	point.payload = {"content": "hola", "summary": "hola"}
	fake_client.scroll.return_value = ([point], None)
	captured: dict = {}

	def fake_set_payload(collection_name, payload, points):
		captured["payload"] = payload

	fake_client.set_payload.side_effect = fake_set_payload

	monkeypatch.setattr(d, "MemoryManager", lambda: fake_mm)
	monkeypatch.setattr(d, "chunk_text", lambda text: ["c1", "c2"])
	monkeypatch.setattr(d, "_is_template_echo", lambda c: False)
	monkeypatch.setattr(d, "audit_engram_quality", lambda s: True)
	monkeypatch.setattr(
		d,
		"distill_engram",
		lambda c: {"emotion": "neutral", "intensity": 0.5, "category": "work"},
	)
	monkeypatch.setattr(d, "merge_relics", lambda distilled: [])
	monkeypatch.setattr(d, "build_emotional_vector", lambda affects: {})
	monkeypatch.setattr(
		d,
		"synthesize_hub_v2",
		lambda distilled: {
			"title": "T",
			"summary": "S",
			"texture": "",
			"texture_parts": ["parte 1", "parte 2"],
		},
	)

	driver = d.DistillJobDriver()
	driver.step({"batch_size": 5, "collections": ["work_memories"]}, {"processed": 0})

	assert captured["payload"]["texture_parts"] == ["parte 1", "parte 2"]
