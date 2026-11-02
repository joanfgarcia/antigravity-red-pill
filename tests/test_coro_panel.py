"""El panel como destinatario (RFC-OBS-006 F3).

Un mensaje al panel no es un sobre: no hay cuerpo al que entregarlo. Se convierte
en una nota del tablón — y si trae fecha, nace sellada. Así existe el destinatario
"anónimo" sin inventar un canal nuevo.
"""

import time

import pytest

from red_pill.coro import service
from red_pill.session import theatre
from red_pill.session.store import SessionRegistry


@pytest.fixture
def db(tmp_path, monkeypatch):
	path = str(tmp_path / "session.db")
	monkeypatch.setattr("red_pill.session.store.get_session_db", lambda: path)
	monkeypatch.setattr("red_pill.core.paths.get_session_db", lambda: path)
	SessionRegistry(path)
	return path


def _session() -> dict:
	return {
		"originator": "opencode:ses_a",
		"continuity_id": "01a00000-0000-7000-8000-00000000000a",
		"mission_id": "repo:sharing",
		"campaign_id": None,
	"role": "task",
	}


@pytest.mark.asyncio
async def test_escribir_al_panel_deja_una_nota(db):
	out = await service.send(_session(), {"verb": "notify", "to": "panel", "body": "revisar P1 el 16"})
	assert "panel" in out and "nota=" in out
	notas = theatre.list_notes(limit=5)
	assert [n["summary"] for n in notas] == ["revisar P1 el 16"]


@pytest.mark.asyncio
async def test_al_panel_se_le_puede_pedir_fecha(db):
	now = time.time()
	out = await service.send(_session(), {"verb": "notify", "to": "panel", "body": "para el futuro", "deliver_in_days": 14})
	assert "sellada hasta" in out
	assert theatre.list_notes(limit=5, now=now + 15 * 86400)[0]["summary"] == "para el futuro"
	assert theatre.list_notes(limit=5, now=now) == []


@pytest.mark.asyncio
async def test_al_panel_sin_cuerpo_no_es_un_error(db):
	"""`body` vacío sigue siendo un error: una nota sin texto no la lee nadie."""
	from red_pill.coro.service import CoroError

	with pytest.raises(CoroError):
		await service.send(_session(), {"verb": "notify", "to": "panel", "body": ""})
