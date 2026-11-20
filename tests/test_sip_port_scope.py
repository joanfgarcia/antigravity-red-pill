"""El centinela del SIP mira SU servidor, no el primer `llama-server` del host.

Incidente 2026-11-19 19:00 → 2026-11-20 03:00: `dokime-llama` (otro producto,
unit aparte) escuchaba en :8080. `_find_llama_port` barría el host con
`pgrep -a llama-server` y aceptaba el primer `--port`: el centinela del SIP
probó :8080, se lo encontró caído y emitió `sip_unhealthy` durante 9 h mientras
el proxy real servía sano en :8760.

Y el heal de esa señal evaporaba `hypervisor_unreachable`, que es de
`drive_evaluator`: enterraba el dolor de otro componente y dejaba viva la señal
propia. Estos tests fijan las dos mitades.
"""

import subprocess
from unittest.mock import MagicMock

from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.check_sip import SIP_SIGNAL_NAMES, SipCheck


def _with_unit(argv, pid=4242):
	"""Un SipCheck cuyo unit declara `pid` y cuyo argv es `argv`."""
	check = SipCheck()
	check._unit_main_pid = lambda: pid  # type: ignore[method-assign]
	check._cmdline = lambda _pid: list(argv)  # type: ignore[method-assign]
	return check


def test_dual_bind_del_unit_gana_al_llama_server_ajeno(monkeypatch):
	"""Un `llama-server` ajeno en :8080 no puede secuestrar el probe."""
	check = _with_unit(["python3", "/x/run_dual_bind.py"])
	host_sweep = MagicMock()
	monkeypatch.setattr(subprocess, "run", host_sweep)

	assert check._find_llama_port() == 8760
	host_sweep.assert_not_called()


def test_llama_server_del_unit_usa_su_propio_port(monkeypatch):
	"""Si el unit ES un llama-server, manda el `--port` de su argv."""
	check = _with_unit(["/usr/bin/llama-server", "-m", "m.gguf", "--port", "51911"])
	host_sweep = MagicMock()
	monkeypatch.setattr(subprocess, "run", host_sweep)

	assert check._find_llama_port() == 51911
	host_sweep.assert_not_called()


def test_unit_sin_puerto_cae_al_barrido_del_host(monkeypatch):
	"""Sin MainPID (unit invisible) se conserva el barrido previo del host."""
	check = SipCheck()
	check._unit_main_pid = lambda: None  # type: ignore[method-assign]

	def fake_run(cmd, **kw):
		class _R:
			stdout = "123 llama-server -m m.gguf --port 43905\n" if cmd[:2] == ["pgrep", "-a"] else ""

		return _R()

	monkeypatch.setattr(subprocess, "run", fake_run)
	assert check._find_llama_port() == 43905


def test_heal_entierra_sus_senales_y_no_las_ajenas(monkeypatch):
	"""El reinicio del SIP cura lo del SIP; `hypervisor_unreachable` no es suya."""
	check = SipCheck()
	monkeypatch.setattr(SipCheck, "_restart_service", lambda self: True)

	evaporated = []

	class _FakeMemory:
		def evaporate_signals(self, name):
			evaporated.append(name)

	monkeypatch.setattr("red_pill.memory.MemoryManager", _FakeMemory)

	assert check.heal_specific(None, AuditFinding(type="sip_unhealthy", severity=7.0, message="x")) is True
	assert set(evaporated) == set(SIP_SIGNAL_NAMES)
	assert "hypervisor_unreachable" not in evaporated
