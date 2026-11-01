"""Sellado del turno: identidad propia, reloj atómico y D2-a.

Lo que se fija aquí, y por qué (medido el 2026-10-30: `session_mirror` con 20.204
filas y **cero** con `global_turn > 0`, o sea `fetch_divergent_turns` sin datos):

1. El `turn_id` es NUESTRO y no cíclico (tiempo + azar), ordenable por ms.
2. El reloj avanza en un solo sitio, dentro de `BEGIN IMMEDIATE` y sin retroceso:
   N escritores concurrentes reciben N números distintos.
3. D2-a: sólo avanza un turno conversacional o con afinidad. Una señal sin
   afinidad no puede inflar `Δ` (que debe significar "turnos paralelos").
4. Un `request_id` vacío o repetido del arnés **no identifica**: se conserva como
   procedencia y el turno lleva identidad propia, así que no se traga el siguiente.
"""

from __future__ import annotations

import threading

import pytest

from red_pill.session import turn_seal


def test_turn_id_no_ciclico_y_ordenable_por_milisegundo() -> None:
	base = 1_700_000_000_000
	a = turn_seal.new_turn_id(base)
	b = turn_seal.new_turn_id(base + 1)
	assert turn_seal.is_valid_turn_id(a)
	assert len(a) == 26
	assert a < b, "el tiempo va delante: ordenable por ms"


def test_turn_id_unico_dentro_del_mismo_milisegundo() -> None:
	base = 1_700_000_000_000
	ids = {turn_seal.new_turn_id(base) for _ in range(2000)}
	assert len(ids) == 2000, "80 bits de azar: sin repeticiones"


def test_turn_id_invalido_no_pasa_por_bueno() -> None:
	for bad in ("", "abc", "I" * 26, "a" * 25 + "!", "a" * 27):
		assert not turn_seal.is_valid_turn_id(bad), bad


@pytest.mark.parametrize(
	("role", "prompt", "response", "affinity", "expected"),
	[
		("user", "hola", "eco", None, True),
		("user", "dolor", "", None, False),
		("user", "", "", None, False),
		("user", "awake", "", ["mission:x"], True),
		("system", "hola", "eco", None, False),
	],
)
def test_d2a_que_avanza_el_reloj(role, prompt, response, affinity, expected) -> None:
	assert turn_seal.advances_clock(role=role, prompt=prompt, response=response, affinity=affinity) is expected


def test_reloj_concurrente_sin_repetir_ni_retroceder(tmp_path) -> None:
	db = str(tmp_path / "session.db")
	n = 25
	seen: list[int] = []
	lock = threading.Lock()

	def worker(i: int) -> None:
		value = turn_seal.next_global_turn(f"opencode:t{i}", None, db_path=db)
		with lock:
			seen.append(value)

	threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
	for t in threads:
		t.start()
	for t in threads:
		t.join()

	assert len(set(seen)) == n, f"números repetidos: {sorted(seen)}"
	assert min(seen) >= 1 and max(seen) <= n, "sin huecos ni saltos"


def test_seal_turn_no_avanza_si_la_politica_dice_que_no(tmp_path) -> None:
	db = str(tmp_path / "session.db")
	sealed = turn_seal.seal_turn(
		originator="opencode:x", role="user", prompt="dolor", response="", db_path=db
	)
	assert sealed["advanced"] is False
	assert sealed["global_turn"] == 0
	assert turn_seal.is_valid_turn_id(sealed["turn_id"]), "la identidad existe aunque no haya reloj"


def test_seal_turn_conserva_el_id_ajeno_como_procedencia(tmp_path) -> None:
	db = str(tmp_path / "session.db")
	sealed = turn_seal.seal_turn(
		originator="opencode:x",
		requested_id="req-que-no-nos-fiamos",
		role="user",
		prompt="hola",
		response="eco",
		db_path=db,
	)
	assert sealed["requested_id"] == "req-que-no-nos-fiamos"
	assert sealed["turn_id"] != sealed["requested_id"], "el ajeno nunca es la identidad"
	assert sealed["global_turn"] == 1


def test_dos_turnos_con_el_mismo_request_id_no_se_pisan(tmp_path) -> None:
	db = str(tmp_path / "session.db")
	a = turn_seal.seal_turn(originator="opencode:x", requested_id="repetido", prompt="uno", response="a", db_path=db)
	b = turn_seal.seal_turn(originator="opencode:x", requested_id="repetido", prompt="dos", response="b", db_path=db)
	assert a["turn_id"] != b["turn_id"], "un id repetido no puede fundir dos turnos"
	assert b["global_turn"] == a["global_turn"] + 1
