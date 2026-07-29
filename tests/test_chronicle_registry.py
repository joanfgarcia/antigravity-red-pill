"""Registro del chronicle diario: multi-fuente, auto-seed y migración (29 jul 2026).

Historia en dos actos. Acto 1 (madrugada del 29 jul): tras la migración XDG el
chronicle re-ingería TODO el histórico cada noche y moría por timeout — cura:
registro en el data dir XDG + auto-seed del histórico en el primer contacto.
Acto 2 (multi-orquestador): el registro pasa de plano (`{cid: steps}`, solo
Antigravity) a anidado por fuente (`{source: {cid: steps}}`); la migración debe
preservar lo sembrado o la primera noche re-ingeriría el histórico entero otra vez.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import chronicle_daily  # noqa: E402

from red_pill.chronicle_sources.base import ChronicleSourcePlugin  # noqa: E402


class StubSource(ChronicleSourcePlugin):
	"""Fuente sintética: conversaciones declaradas en memoria."""

	session_prefix = "stub:"

	def __init__(self, name, conversations):
		self.name = name
		self.conversations = dict(conversations)  # cid -> step_count

	def discover(self):
		return sorted(self.conversations.items())

	def load(self, conversation_id):
		return [{"role": "user", "content": f"hola desde {conversation_id}", "timestamp": None}]


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
	registry_path = tmp_path / "registry.json"
	monkeypatch.setattr(chronicle_daily, "PROCESSED_LOG", registry_path)
	return registry_path


def test_autoseed_marks_history_processed_per_source(isolated_registry):
	"""Sin registro previo, cada fuente siembra su histórico como procesado: la
	primera ejecución es nominal e instantánea en vez de una re-ingesta masiva
	abatida por la cota del job."""
	plugins = [StubSource("alpha", {"ses_a": 12}), StubSource("beta", {"ses_b": 40, "ses_c": 7})]
	state = chronicle_daily._load_processed()

	assert chronicle_daily._seed_new_sources(state, plugins) is True
	assert state["registry"] == {"alpha": {"ses_a": 12}, "beta": {"ses_b": 40, "ses_c": 7}}
	assert set(state["processed"]["beta"]) == {"ses_b", "ses_c"}
	assert chronicle_daily._find_pending(state, plugins) == []  # nada pendiente tras sembrar


def test_only_deltas_are_pending_after_seed(isolated_registry):
	"""Una conversación que crece (más steps que lo registrado) sí entra, y solo
	en su fuente — las demás no se ven arrastradas."""
	alpha = StubSource("alpha", {"ses_a": 12})
	beta = StubSource("beta", {"ses_b": 40})
	state = chronicle_daily._load_processed()
	chronicle_daily._seed_new_sources(state, [alpha, beta])

	beta.conversations["ses_b"] = 55
	pending = chronicle_daily._find_pending(state, [alpha, beta])
	assert [(p.name, cid, steps) for p, cid, steps in pending] == [("beta", "ses_b", 55)]


def test_new_source_seeds_without_touching_existing(isolated_registry):
	"""Registro ya poblado + fuente nueva habilitada: la nueva siembra su
	histórico, las veteranas siguen a deltas."""
	alpha = StubSource("alpha", {"ses_a": 12})
	state = chronicle_daily._load_processed()
	chronicle_daily._seed_new_sources(state, [alpha])

	gamma = StubSource("gamma", {"ses_g": 99})
	assert chronicle_daily._seed_new_sources(state, [alpha, gamma]) is True
	assert state["registry"]["alpha"] == {"ses_a": 12}
	assert state["registry"]["gamma"] == {"ses_g": 99}
	assert chronicle_daily._find_pending(state, [alpha, gamma]) == []


def test_force_all_reprocesses_everything(isolated_registry):
	"""`--all` es la vía de escape: reprocesa el histórico completo de todas las
	fuentes aunque el registro lo dé por hecho."""
	plugins = [StubSource("alpha", {"ses_a": 12}), StubSource("beta", {"ses_b": 40})]
	state = chronicle_daily._load_processed()
	chronicle_daily._seed_new_sources(state, plugins)

	pending = chronicle_daily._find_pending(state, plugins, force_all=True)
	assert len(pending) == 2


def test_flat_registry_migrates_to_antigravity_source(isolated_registry):
	"""El registro plano heredado (solo Antigravity) migra a anidado por fuente
	sin perder lo sembrado — y se persiste migrado."""
	legacy = {
		"processed": {"cid-1": "2026-07-29T08:05:21", "cid-2": "2026-07-29T08:05:21"},
		"registry": {"cid-1": 1000, "cid-2": 480},
		"last_run": "2026-07-29T08:34:28",
		"stats": {"total_ingested": 0, "total_sessions": 2},
	}
	isolated_registry.write_text(json.dumps(legacy), encoding="utf-8")

	state = chronicle_daily._load_processed()
	assert state["registry"] == {"antigravity": {"cid-1": 1000, "cid-2": 480}}
	assert state["processed"] == {"antigravity": legacy["processed"]}

	persisted = json.loads(isolated_registry.read_text(encoding="utf-8"))
	assert persisted["registry"] == state["registry"]

	# La fuente antigravity ya existe: no re-siembra ni re-ingiere el histórico
	antigravity = StubSource("antigravity", {"cid-1": 1000, "cid-2": 480})
	assert chronicle_daily._seed_new_sources(state, [antigravity]) is False
	assert chronicle_daily._find_pending(state, [antigravity]) == []


def test_nested_registry_is_not_migrated_twice(isolated_registry):
	"""Un registro ya anidado pasa intacto por la migración (idempotencia)."""
	nested = {
		"processed": {"antigravity": {"cid-1": "2026-07-29T08:05:21"}},
		"registry": {"antigravity": {"cid-1": 1000}},
		"last_run": None,
		"stats": {"total_ingested": 0, "total_sessions": 1},
	}
	isolated_registry.write_text(json.dumps(nested), encoding="utf-8")

	state = chronicle_daily._load_processed()
	assert state["registry"] == nested["registry"]
	assert state["processed"] == nested["processed"]


def test_failed_discovery_does_not_break_other_sources(isolated_registry):
	"""Una fuente rota (DB bloqueada, dir ausente) no tumba el barrido de las demás."""

	class BrokenSource(StubSource):
		def discover(self):
			raise RuntimeError("db locked")

	alpha = StubSource("alpha", {"ses_a": 12})
	state = chronicle_daily._load_processed()
	chronicle_daily._seed_new_sources(state, [alpha])
	alpha.conversations["ses_a"] = 20

	pending = chronicle_daily._find_pending(state, [BrokenSource("broken", {}), alpha])
	assert [(p.name, cid, steps) for p, cid, steps in pending] == [("alpha", "ses_a", 20)]
