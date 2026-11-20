"""Identidad del `llama-server` propio (core.llama_identity).

Caso origen: el probe de GPU del DAG leía el `-ngl` del **primer**
`llama-server` de `pgrep` — el del vecino. Un vecino en CPU (`-ngl 0`)
difería para siempre cada etapa `requires_gpu`; uno en GPU (`-ngl 99`) la
dejaba pasar aunque el nuestro sirviera en CPU. Familia del `:8080` que el
centinela del SIP tomó por el proxy propio (2026-11-19/20).
"""

from __future__ import annotations

import red_pill.core.llama_identity as li

# ── parse_ngl: las tres formas de llama.cpp y el silencio ────────────────────


def test_parse_ngl_tres_formas():
	assert li.parse_ngl(["llama-server", "-ngl", "33"]) == 33
	assert li.parse_ngl(["llama-server", "-ngl=33"]) == 33
	assert li.parse_ngl(["llama-server", "-ngl33"]) == 33


def test_parse_ngl_ausente_o_no_numerico_es_none():
	assert li.parse_ngl(["llama-server", "-m", "x.gguf"]) is None
	assert li.parse_ngl(["llama-server", "-ngl", "abc"]) is None
	assert li.parse_ngl(["llama-server", "-ngl"]) is None


# ── own_llama_pids: la identidad la da el unit, no el host ───────────────────


def test_own_llama_pids_solo_los_hijos_del_unit(monkeypatch):
	"""(dual-bind MainPID ≠ llama-server) → solo los hijos que SON llama-server."""
	argv = {
		100: ["python3", "/home/joan/.local/share/red-pill/daemon/run_dual_bind.py"],
		101: ["/usr/local/bin/llama-server", "-m", "model.gguf", "-ngl", "99"],
		102: ["/usr/bin/python3", "logger.py"],
	}
	monkeypatch.setattr(li, "unit_main_pid", lambda unit=None: 100)
	monkeypatch.setattr(li, "cmdline", lambda pid: argv.get(int(pid), []))
	monkeypatch.setattr(li, "child_pids", lambda pid: [101, 102])
	assert li.own_llama_pids() == [101]


def test_own_llama_pids_unit_que_es_el_propio_llama_server(monkeypatch):
	"""Setup sin proxy: el MainPID ES el `llama-server`."""
	monkeypatch.setattr(li, "unit_main_pid", lambda unit=None: 200)
	monkeypatch.setattr(li, "cmdline", lambda pid: ["/usr/local/bin/llama-server", "--port", "8760"])
	monkeypatch.setattr(li, "child_pids", lambda pid: [])
	assert li.own_llama_pids() == [200]


def test_own_llama_pids_unit_caido_es_vacio(monkeypatch):
	"""Sin MainPID no hay identidad: lista vacía (no se cae al barrido del host)."""
	monkeypatch.setattr(li, "unit_main_pid", lambda unit=None: None)
	assert li.own_llama_pids() == []


# ── own_ngl: el vecino no vota ───────────────────────────────────────────────


def test_own_ngl_ignora_al_vecino(monkeypatch):
	"""Con un vecino en CPU en el host, el `-ngl` sigue siendo el del unit."""
	monkeypatch.setattr(li, "unit_main_pid", lambda unit=None: 100)
	monkeypatch.setattr(
		li,
		"cmdline",
		lambda pid: {
			100: ["python3", "run_dual_bind.py"],
			101: ["llama-server", "-ngl", "99"],
		}.get(int(pid), []),
	)
	monkeypatch.setattr(li, "child_pids", lambda pid: [101])
	assert li.own_ngl() == 99


def test_own_ngl_varios_propios_toma_el_menor(monkeypatch):
	"""Dos servidores nuestros: si uno sirve en CPU, la etapa GPU no pasa."""
	monkeypatch.setattr(li, "unit_main_pid", lambda unit=None: 100)
	monkeypatch.setattr(
		li,
		"cmdline",
		lambda pid: {
			100: ["python3", "run_dual_bind.py"],
			101: ["llama-server", "-ngl", "99"],
			102: ["llama-server", "-ngl", "0"],
		}.get(int(pid), []),
	)
	monkeypatch.setattr(li, "child_pids", lambda pid: [101, 102])
	assert li.own_ngl() == 0


def test_own_ngl_sin_proceso_propio_es_desconocido(monkeypatch):
	"""Sin proceso propio → -1 (desconocido); nunca el `-ngl` de un ajeno."""
	monkeypatch.setattr(li, "unit_main_pid", lambda unit=None: None)
	assert li.own_ngl() == -1
