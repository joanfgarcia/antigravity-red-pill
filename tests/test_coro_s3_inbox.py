"""S3 (AD-095): el `[CORO]` del handshake cuenta el inbox y enseña el sobre.

El digest contaba actas del teatro, misiones vivas y novedades de la misión, pero
no la **correspondencia directa**: un mensaje de otra alma esperaba en el buzón y
el turno no lo sabía hasta abrir `coro_api.fetch`. S3 añade el recuento y el
sobre (con `respuesta: SÍ/NO` visible) al texto que se inyecta al despertar.
"""

import time

import pytest

from red_pill.mcp_server import _coro_digest
from red_pill.session.store import SessionRegistry

A = "01a187ba-a9f6-718d-b9e1-d531b8d7a947"
B = "01a186e6-f48d-7491-a1d0-7ec130fa1a68"


@pytest.fixture
def reg(tmp_path, monkeypatch):
	"""Registro temporal; el digest construye `SessionRegistry()` sin ruta."""
	path = str(tmp_path / "session.db")
	monkeypatch.setattr("red_pill.session.store.get_session_db", lambda: path)
	monkeypatch.setattr("red_pill.core.paths.get_session_db", lambda: path)
	r = SessionRegistry(path)
	r.upsert_session(originator="opencode:ses_a", continuity_id=A, mission_id="repo:next")
	r.upsert_session(originator="opencode:ses_b", continuity_id=B, mission_id="repo:next")
	return r


def _carta(reg, *, verb="ask", expects_reply=True, summary="¿puedes revisar el dolor?"):
	return reg.add_event(
		event_type="message",
		mission_id="repo:next",
		continuity_id=B,  # el tablón es de quien escribe
		originator="opencode:ses_b",
		summary=summary,
		to_continuity=A,
		verb=verb,
		thread_id="hilo-s3",
		hop=1,
		hop_max=8,
		expects_reply=expects_reply,
		value_class="now",
		expires_at=time.time() + 86400,
	)


def _identidad(seq=0):
	return {
		"continuity_id": A,
		"originator": "opencode:ses_a",
		"mission_id": "repo:next",
		"role": "task",
		"previous_event_seq": seq,
	}


def test_count_inbox_cuenta_solo_lo_dirigido_a_mi(reg):
	_carta(reg)
	reg.add_event(event_type="commit", mission_id="repo:next", summary="commit suelto", continuity_id=B)
	assert reg.count_inbox(A) == 1
	assert reg.count_inbox(B) == 0


def test_el_digest_cuenta_la_carta_y_muestra_el_sobre(reg):
	_carta(reg)

	out = _coro_digest(_identidad(), until_seq=reg.get_max_event_seq())

	assert out is not None
	assert "1 carta sin abrir" in out
	# El sobre completo: verbo, hilo, salto y si hay que responder.
	assert "CORO ask" in out and "hilo-s3" in out
	assert "respuesta: SÍ" in out
	assert "de:" in out


def test_sin_cartas_ni_novedades_el_digest_call_a(reg):
	assert _coro_digest(_identidad(), until_seq=0) is None


def test_varias_cartas_resume_las_que_no_caben(reg):
	for i in range(5):
		_carta(reg, summary=f"carta {i}")

	out = _coro_digest(_identidad(), until_seq=reg.get_max_event_seq())

	assert "5 cartas sin abrir" in out
	assert "y 2 más" in out
