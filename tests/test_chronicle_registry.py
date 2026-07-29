"""Registro del chronicle diario: ruta XDG + auto-seed (madrugada del 29 jul 2026).

Tras la migración XDG, el chronicle buscaba su registro en la ruta heredada
`~/.agent/chronicle_processed.json` (inexistente) y re-ingería TODO el histórico
cada noche — como job con cota de 60 min, moría por timeout sin llegar a guardar
progreso jamás. El fix del despertar autónomo: registro en el data dir XDG y
auto-seed que marca el histórico como procesado en el primer contacto (solo se
ingieren deltas; `--all` fuerza el reproceso completo).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import chronicle_daily  # noqa: E402


@pytest.fixture
def conversations(tmp_path, monkeypatch):
	"""Directorio de conversaciones simulado + registro aislado en tmp."""
	convo_dir = tmp_path / "unencrypted"
	convo_dir.mkdir()
	for cid, steps in (("ses_aaa", 12), ("ses_bbb", 40)):
		(convo_dir / f"{cid}.json").write_text(json.dumps({"step_count": steps}), encoding="utf-8")
	monkeypatch.setattr("red_pill.core.paths.get_unencrypted_conversations_dir", lambda: convo_dir)
	monkeypatch.setattr(chronicle_daily, "PROCESSED_LOG", tmp_path / "registry.json")
	return convo_dir


def test_autoseed_marks_history_processed_without_ingesting(conversations, tmp_path):
	"""Sin registro previo, el histórico se siembra como procesado: la primera
	ejecución es nominal e instantánea en vez de una re-ingesta masiva abatida
	por la cota del job."""
	state = chronicle_daily._load_processed()

	assert state["registry"] == {"ses_aaa": 12, "ses_bbb": 40}
	assert set(state["processed"]) == {"ses_aaa", "ses_bbb"}
	assert (tmp_path / "registry.json").exists()  # persistido para la próxima
	assert chronicle_daily._find_pending(state) == []  # nada pendiente tras sembrar


def test_only_deltas_are_pending_after_seed(conversations):
	"""Una conversación que crece (más steps que lo registrado) sí entra."""
	state = chronicle_daily._load_processed()
	grown = conversations / "ses_bbb.json"
	grown.write_text(json.dumps({"step_count": 55}), encoding="utf-8")

	pending = chronicle_daily._find_pending(state)
	assert [(p.name, s) for p, s in pending] == [("ses_bbb.json", 55)]


def test_force_all_reprocesses_everything(conversations):
	"""`--all` es la vía de escape: reprocesa el histórico completo aunque el
	registro lo dé por hecho."""
	state = chronicle_daily._load_processed()
	pending = chronicle_daily._find_pending(state, force_all=True)
	assert len(pending) == 2
