"""E2E de la sala de guerra global + digest (RFC_CONSCIENCIA — la "awareness" de turno).

Lo que el Operador ve al abrir turno: el digest del interceptor 12
(`SessionSyncPlugin`) y el tablón global (`build_board`/`render_board`, la fuente
del MCP `session_board`), montados sobre las piezas REALES — registro SQLite,
latidos en disco y reloj global de turnos — sin sesiones reales ni red:

- El registro vive en una BD temporal (`SessionRegistry` → `session.db` en `tmp_path`).
- Los latidos son ficheros `.start`/`.end` reales bajo un STATE_DIR temporal,
  envejecidos con `os.utime`: sesión "muerta" = latido viejo.
- Nunca se lee el `opencode.db` del operador ni Qdrant (rutas inexistentes /
  cliente desactivado).

# Escena base: YO + 2 vivas en la misma misión + 2 vivas en misiones distintas
# (una de ellas en la mía) + 1 muerta.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import red_pill.core.origins as origins
import red_pill.core.session_index as si
import red_pill.core.session_liveness as sl
import red_pill.session.store as store_mod
from red_pill.core.session_liveness import touch_session
from red_pill.session.store import SessionRegistry

# El módulo empieza con dígitos: importlib (convención de los tests del interceptor).
mod = importlib.import_module("red_pill.interceptors.12_session_sync")

ME = "opencode:me"
MY_MISSION = "repo:next"
DEAD_AGE_S = 6 * 3600.0  # muy por encima de SESSION_ACTIVE_MIN (10 min)


# ── Infra: sala de guerra simulada ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def war_room(tmp_path, monkeypatch):
	"""Registro, latidos, orígenes y reloj en `tmp_path`; nunca el estado del operador."""
	monkeypatch.setattr(sl, "get_state_dir", lambda: tmp_path)
	monkeypatch.setattr(origins, "get_state_dir", lambda: tmp_path)
	monkeypatch.setattr(store_mod, "get_session_db", lambda: tmp_path / "session.db")
	# El tablón no debe tocar `opencode.db` ni Qdrant: inexistente el primero, sin cliente.
	monkeypatch.setattr(si, "_opencode_db_path", lambda: tmp_path / "no-opencode.db")
	monkeypatch.setattr(si, "_theme_client", lambda: None)
	monkeypatch.setattr(si, "_INFER_CACHE", {})
	monkeypatch.delenv("SESSION_BOARD_REGISTRY_TTL_H", raising=False)
	monkeypatch.setenv("REDPILL_ORIGINATOR", ME)
	return tmp_path


def _registry() -> SessionRegistry:
	"""El registro REAL, sobre la BD temporal del fixture."""
	return SessionRegistry()


def _beat(
	provider: str,
	session: str,
	*,
	mission: str = "",
	role: str = "task",
	alive: bool = True,
	age_s: float = 10.0,
	end_age_s: float | None = None,
	continuity: str = "",
	**registry_fields,
) -> None:
	"""Latido + alta en el registro de UNA sesión de la sala de guerra.

	Viva = `.start` reciente (sin `.end` posterior → además "en vuelo");
	muerta = latido envejecido más allá de `SESSION_ACTIVE_MIN`."""
	start = touch_session(provider, session, "start")
	assert start is not None and start.exists(), f"el latido .start de {session} no se escribió"
	_age(start, age_s if alive else DEAD_AGE_S)
	if end_age_s is not None:
		end = touch_session(provider, session, "end")
		assert end is not None
		_age(end, end_age_s)
	row = {
		"originator": f"{provider}:{session}",
		"continuity_id": continuity or f"soul-{session}",
		"mission_id": mission or f"repo:{session}",
		"role": role,
	}
	row.update(registry_fields)
	_registry().upsert_session(**row)


def _age(path: Path, seconds: float) -> None:
	"""Envejece un latido: la `mtime` ES la señal de vida (RFC-DESPERTAR-001 P4)."""
	stamp = time.time() - seconds
	os.utime(path, (stamp, stamp))


def _digest(mode: str, *, active_min: int = 10) -> str:
	"""Ejecuta el interceptor de verdad (plugin nuevo en cada llamada: sin caché)."""
	values = {"SESSION_SYNC_MODE": mode, "SESSION_ACTIVE_MIN": active_min}
	p = mod.SessionSyncPlugin()
	with patch.object(mod, "_conf", lambda name, default: values.get(name, default)):
		return asyncio.run(p.execute("abrir turno"))


def _scene() -> int:
	"""YO + 2 vivas en la misma misión + 2 vivas en misiones distintas + 1 muerta.

	- `alfa`/`bravo` comparten misión → el bucket con dos entradas.
	- `echo` está en MI misión → comprueba que no me cuento pero el otro sí.
	- `charlie` está solo en su misión.
	- `delta` murió a medio turno: `.start` de hace 6 h sin `.end` → latido viejo.

	Devuelve el `global_turn` del reloj (un turno por sesión viva menos la mía)."""
	reg = _registry()
	_beat("opencode", "me", mission=MY_MISSION, role="job")
	_beat("opencode", "alfa", mission="repo:sharing", role="task")
	reg.next_global_turn("opencode:alfa")
	_beat("claude", "bravo", mission="repo:sharing", role="job")
	reg.next_global_turn("claude:bravo")
	_beat("opencode", "charlie", mission="repo:neon", role="task")
	reg.next_global_turn("opencode:charlie")
	_beat("claude", "echo", mission=MY_MISSION, role="task")
	_beat("claude", "delta", mission="repo:fantasma", role="task", alive=False)
	return reg.get_max_global_turn()


def _missions(text: str) -> dict:
	"""`misión -> nº declarado por su cabecera` (mismo formato en digest y tablón)."""
	out = {}
	for line in text.splitlines():
		if line.startswith("## "):
			head, _, count = line.rpartition(" (")
			out[head[3:].strip("'")] = int(count.rstrip(")"))
	return out


# ── HEADER: agrupa por misión y cuenta bien las vivas ──────────────────────


def test_header_groups_by_mission_and_counts_live_sessions():
	turn = _scene()

	out = _digest("header")

	assert f"global_turn={turn}" in out
	# Las vivas son las OTRAS: yo no me cuento (5 vivas en escena, 4 ajenas).
	assert "4 otra(s) viva(s)" in out
	# Agrupación por misión: sharing junta a alfa+bravo; echo entra en la mía.
	assert _missions(out) == {"repo:sharing": 2, "repo:neon": 1, MY_MISSION: 1}
	# Muerta (latido viejo) → ni su misión aparece en el digest.
	assert "repo:fantasma" not in out
	# Estado por entrada: `.start` sin `.end` posterior → turno en vuelo.
	assert "en vuelo" in out
	assert "job" in out and "task" in out


def test_closed_turn_is_not_live_but_stale_beat_is_dead():
	"""`.end` posterior al `.start` = turno cerrado: ya no cuenta como viva."""
	_beat("opencode", "me", mission=MY_MISSION, role="job", age_s=40.0, end_age_s=5.0)
	_beat("opencode", "alfa", mission="repo:sharing", role="task", age_s=40.0, end_age_s=20.0)
	_beat("claude", "bravo", mission="repo:neon", role="job")

	out = _digest("header")

	# Solo bravo tiene el turno en vuelo; alfa cerró y desaparece del conteo.
	assert "1 otra(s) viva(s)" in out
	assert _missions(out) == {"repo:neon": 1}
	assert "repo:sharing" not in out


def test_header_without_others_says_so():
	_beat("opencode", "me", mission=MY_MISSION, role="job")
	out = _digest("header")
	assert "(sin otras sesiones vivas)" in out
	assert _missions(out) == {}


# ── MINIMAL: cuenta solo las OTRAS (no se cuenta a sí misma) ───────────────


def test_minimal_counts_only_other_sessions():
	turn = _scene()

	out = _digest("minimal")

	assert "\n" not in out
	assert out == f"[SYNC: 4 otra(s) viva(s) · global_turn={turn}]"


def test_minimal_ignores_my_own_beat():
	"""Con solo la mía viva, el conteo ajeno es 0 (el digest no habla de sí mismo)."""
	_beat("opencode", "me", mission=MY_MISSION, role="job")
	assert _digest("minimal") == "[SYNC: 0 otra(s) viva(s) · global_turn=0]"


def test_minimal_drops_dead_sessions():
	_beat("opencode", "me", mission=MY_MISSION, role="job")
	_beat("claude", "delta", mission="repo:fantasma", alive=False)
	_beat("opencode", "alfa", mission="repo:sharing")
	assert _digest("minimal") == "[SYNC: 1 otra(s) viva(s) · global_turn=0]"


# ── SILENT: el default no consulta NADA ────────────────────────────────────


def test_silent_is_the_default_and_reads_nothing():
	_scene()
	p = mod.SessionSyncPlugin()
	boom = AssertionError("SILENT no debe consultar NADA")
	with (
		patch.object(p, "_live_signals", side_effect=boom),
		patch.object(p, "_global_turn", side_effect=boom),
		patch.object(p, "_registry_rows", side_effect=boom),
		patch.object(mod, "_conf", lambda name, default: default),
	):
		assert asyncio.run(p.execute("hola")) == ""


# ── Pendientes: aviso del digest con eventos reales de misión ──────────────


def test_header_notices_pending_events_of_my_mission_only():
	_beat("opencode", "me", mission=MY_MISSION, role="job", last_seen_event_seq=0)
	reg = _registry()
	reg.add_event(event_type="phase_done", mission_id=MY_MISSION, summary="B1 cerrada", originator="opencode:charlie")
	reg.add_event(event_type="commit", mission_id=MY_MISSION, summary="abc1234", originator="opencode:charlie")
	reg.add_event(event_type="phase_done", mission_id="repo:otro", summary="no es mi misión", originator="opencode:alfa")

	out = _digest("header")

	notice = out.split("Pendientes:", 1)[1]
	assert "2 evento(s)" in notice
	assert MY_MISSION in notice


# ── Tablón global (fuente del MCP `session_board`) ─────────────────────────


def test_build_board_marks_live_and_dead():
	_scene()

	board = si.build_board()

	by = {f"{b['provider']}:{b['session_id']}": b for b in board}
	assert set(by) == {"opencode:me", "opencode:alfa", "claude:bravo", "opencode:charlie", "claude:echo", "claude:delta"}
	# Vivo = latido reciente en vuelo; muerto = latido viejo → inactiva, no desaparece.
	assert by["opencode:me"]["active"] is True
	assert by["claude:bravo"]["active"] is True
	assert by["claude:echo"]["active"] is True
	assert by["claude:delta"]["active"] is False
	# El registro enriquece el latido: misión / rol / alma.
	assert by["opencode:charlie"]["mission_id"] == "repo:neon"
	assert by["claude:echo"]["mission_id"] == MY_MISSION
	assert by["opencode:alfa"]["role"] == "task"
	assert by["claude:bravo"]["continuity_id"] == "soul-bravo"


def test_render_board_groups_by_mission_and_totals():
	_scene()

	text = si.render_board(si.build_board())

	head = text.splitlines()[0]
	assert "5 viva(s)" in head  # yo + alfa + bravo + charlie + echo (delta no)
	assert "1 reciente(s)" in head  # delta, con latido viejo
	assert "4 misión(es)" in head
	# Agrupación global (a diferencia del digest, aquí YO también cuento en mi misión).
	assert _missions(text) == {"repo:sharing": 2, "repo:neon": 1, MY_MISSION: 2, "repo:fantasma": 1}
	# La muerta se muestra, pero no como viva: latido viejo en vuelo = huérfana.
	delta_line = next(line for line in text.splitlines() if "delta" in line)
	assert "huérfana" in delta_line


def test_render_board_closed_turn_is_idle():
	"""Turno cerrado (`.end` posterior) y reciente → sigue en el tablón, pero idle."""
	_beat("opencode", "alfa", mission="repo:sharing", age_s=40.0, end_age_s=20.0)

	text = si.render_board(si.build_board())

	assert "0 viva(s)" in text.splitlines()[0]
	assert "1 reciente(s)" in text.splitlines()[0]
	alfa_line = next(line for line in text.splitlines() if "alfa" in line)
	assert "idle" in alfa_line


def test_render_board_empty_room():
	assert si.render_board([]) == "[SESSION BOARD] Sin sesiones vivas ni recientes."
