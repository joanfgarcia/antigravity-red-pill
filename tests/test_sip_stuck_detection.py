"""SIP stuck-inference: ocupado no es atascado.

Incidente 2026-11-03 01:00: el centinela dejó un CRITICAL `sip_stuck`
("llama-server stuck in inference loop, CPU 653%, port 43905") sobre un
servidor que llevaba 2 h sirviendo una completion cada ~27 s al ciclo
nocturno. La causa: el probe de 1 token tenía 5 s de techo y el SIP corre con
`-np 1`, así que el probe hacía cola detrás de la generación en curso y
expiraba. Un servidor ocupado se leía como un servidor muerto.

Estos tests fijan la distinción: ocupado (y contesta) no es finding; mudo
incluso con presupuesto de cola sí lo es."""

from red_pill.metabolism.sentinel_plugins.check_sip import INFERENCE_TEST_TIMEOUT_S, SipCheck


class _FakeSip(SipCheck):
	def __init__(self, slot_busy, probe_ok, cpu_pct=653.0):
		self._busy = slot_busy
		self._probe_ok = probe_ok
		self._cpu = cpu_pct
		self.probe_budgets = []

	def _slot_busy(self, port):
		return self._busy

	def _probe_completes(self, port, budget_s):
		self.probe_budgets.append(budget_s)
		return self._probe_ok

	def _get_llama_cpu(self):
		return self._cpu

	def _find_llama_port(self):
		return 43905


def _health_ok(monkeypatch):
	"""Salta el /health real: el objeto solo se usa para `resp.status`."""

	class _Resp:
		status = 200

		class _Ctx:
			def __enter__(self):
				return self

			def __exit__(self, *a):
				return False

		def __enter__(self):
			return self

	def fake_urlopen(url, *a, **kw):
		if "/health" in url:
			return _Resp()
		raise AssertionError(f"urlopen inesperado: {url}")

	monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def test_servidor_ocupado_que_contesta_no_es_stuck(monkeypatch):
	"""Regresión: 653% de CPU sirviendo el ciclo nocturno no es un hallazgo."""
	_health_ok(monkeypatch)
	fake = _FakeSip(slot_busy=True, probe_ok=True)
	assert fake.audit_health(cfg=None) == []
	# Slot ocupado → se le da presupuesto de cola, no el techo corto.
	assert fake.probe_budgets == [65.0]


def test_slot_libre_usa_presupuesto_corto(monkeypatch):
	"""Sin nada en vuelo no hay cola que esperar: la detección es inmediata."""
	_health_ok(monkeypatch)
	fake = _FakeSip(slot_busy=False, probe_ok=True)
	assert fake.audit_health(cfg=None) == []
	assert fake.probe_budgets == [INFERENCE_TEST_TIMEOUT_S]


def test_mudo_con_slot_ocupado_es_stuck(monkeypatch):
	"""Una generación que no avanza nunca sí es un atasco."""
	_health_ok(monkeypatch)
	fake = _FakeSip(slot_busy=True, probe_ok=False)
	findings = fake.audit_health(cfg=None)
	assert [f.type for f in findings] == ["sip_stuck"]
	assert findings[0].severity == 9.0


def test_mudo_con_slot_libre_es_stuck(monkeypatch):
	_health_ok(monkeypatch)
	fake = _FakeSip(slot_busy=False, probe_ok=False)
	assert [f.type for f in fake.audit_health(cfg=None)] == ["sip_stuck"]


def test_endpoint_slots_ausente_da_presupuesto_largo(monkeypatch):
	"""Si el servidor no informa de sus slots, no inventamos cola: presupuesto largo."""
	_health_ok(monkeypatch)
	fake = _FakeSip(slot_busy=None, probe_ok=True)
	assert fake.audit_health(cfg=None) == []
	assert fake.probe_budgets == [65.0]


def test_cpu_baja_no_dispara_probe(monkeypatch):
	"""Sin fiebre de CPU no se molesta al servidor."""
	_health_ok(monkeypatch)
	fake = _FakeSip(slot_busy=True, probe_ok=False, cpu_pct=12.0)
	assert fake.audit_health(cfg=None) == []
	assert fake.probe_budgets == []
