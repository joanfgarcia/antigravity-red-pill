"""Reconciliación del dolor (RFC-OBS-005 P0) — report-only, con guardas.

El dolor del auditor tiene que morir cuando muere su causa, pero no puede morir
por un veredicto falso: sin veredicto no se borra, un evento no se reconcilia, y
solo se tocan las señales del propio auditor. P0 no borra: calcula y registra.
"""

from pathlib import Path

from red_pill.metabolism.reconcile import VERDICT_ERROR, VERDICT_OK, VERDICT_SKIPPED, AuditRound, reconcile


class FakeMemory:
	def __init__(self, signals=None):
		self.signals = signals or []
		self.evaporated = []

	def signals_by_source(self, source):
		return [s for s in self.signals if s.get("signal_source") == source]

	def evaporate_signals(self, name):
		self.evaporated.append(name)
		return 1


def _signal(name, source="SentinelAuditor", intensity=8.0, age=12.0):
	return {"name": name, "signal_source": source, "intensity": intensity, "age_hours": age}


def _round(emitted=(), preserved=(), verdict=VERDICT_OK, complete=True):
	r = AuditRound(round_id="t1")
	r.record("repo:sharing", verdict, emitted, preserved)
	r.complete = complete
	return r


class TestReportOnly:
	def test_primera_ausencia_no_evapora(self, tmp_path):
		mem = FakeMemory([_signal("signal_hung_service_failure")])
		report = reconcile(_round(), mem, state_dir=tmp_path)
		assert report["absent"] == ["signal_hung_service_failure"]
		assert report["would_evaporate"] == []
		assert mem.evaporated == []

	def test_segunda_ausencia_marca_pero_no_borra(self, tmp_path):
		mem = FakeMemory([_signal("signal_hung_service_failure")])
		reconcile(_round(), mem, state_dir=tmp_path)
		report = reconcile(_round(), mem, state_dir=tmp_path)
		assert report["would_evaporate"] == ["signal_hung_service_failure"]
		assert mem.evaporated == []  # report-only

	def test_emitida_resetea_la_cuenta(self, tmp_path):
		mem = FakeMemory([_signal("signal_hung_service_failure")])
		reconcile(_round(), mem, state_dir=tmp_path)
		reconcile(_round(emitted=["signal_hung_service_failure"]), mem, state_dir=tmp_path)
		report = reconcile(_round(), mem, state_dir=tmp_path)
		assert report["would_evaporate"] == []

	def test_artefacto_persistido(self, tmp_path):
		mem = FakeMemory([_signal("signal_hung_service_failure")])
		reconcile(_round(), mem, state_dir=tmp_path)
		assert (tmp_path / "auditor_round.json").exists()
		assert (tmp_path / "signal_absences.json").exists()


class TestGuardas:
	def test_sin_veredicto_se_preserva(self, tmp_path):
		mem = FakeMemory([_signal("signal_test_failure")])
		r = _round(verdict=VERDICT_ERROR, preserved=["signal_test_failure"])
		report = reconcile(r, mem, state_dir=tmp_path)
		assert report["absent"] == []
		assert mem.evaporated == []

	def test_paso_saltado_se_preserva(self, tmp_path):
		mem = FakeMemory([_signal("signal_typing_failure")])
		r = _round(verdict=VERDICT_SKIPPED, preserved=["signal_typing_failure"])
		report = reconcile(r, mem, state_dir=tmp_path)
		assert report["absent"] == []

	def test_evento_no_es_candidato(self, tmp_path):
		mem = FakeMemory([_signal("signal_interaction_unrendered_purged_failure")])
		report = reconcile(_round(), mem, state_dir=tmp_path)
		assert report["candidates"] == []
		assert report["absent"] == []

	def test_otro_emisor_no_se_toca(self, tmp_path):
		mem = FakeMemory([_signal("jobs_frustrated", source="JobMonitor")])
		report = reconcile(_round(), mem, state_dir=tmp_path)
		assert report["candidates"] == []
		assert mem.evaporated == []

	def test_ronda_incompleta_no_reconcilia(self, tmp_path):
		mem = FakeMemory([_signal("signal_hung_service_failure")])
		report = reconcile(_round(complete=False), mem, state_dir=tmp_path)
		assert report["skipped"] == "incomplete_round"
		assert mem.evaporated == []

	def test_interruptor_apagado(self, tmp_path):
		mem = FakeMemory([_signal("signal_hung_service_failure")])
		report = reconcile(_round(), mem, policy={"enabled": False}, state_dir=tmp_path)
		assert report["skipped"] == "disabled"


class TestActivacion:
	def test_con_report_only_off_borra_y_registra_edad(self, tmp_path):
		mem = FakeMemory([_signal("signal_hung_service_failure", intensity=9.0, age=32.7)])
		policy = {"report_only": False}
		reconcile(_round(), mem, policy=policy, state_dir=tmp_path)
		report = reconcile(_round(), mem, policy=policy, state_dir=tmp_path)
		assert mem.evaporated == ["signal_hung_service_failure"]
		assert report["evaporated"][0]["age_hours"] == 32.7
		assert report["evaporated"][0]["intensity"] == 9.0

	def test_ausencias_configurables(self, tmp_path):
		mem = FakeMemory([_signal("signal_hung_service_failure")])
		policy = {"report_only": False, "absences": 1}
		report = reconcile(_round(), mem, policy=policy, state_dir=tmp_path)
		assert mem.evaporated == ["signal_hung_service_failure"]
		assert report["evaporated"]


class TestConfig:
	def test_service_down_es_reconciliable_y_el_evento_no(self):
		from red_pill.metabolism.signal_profiles import load_catalog

		catalog = load_catalog(force=True)
		assert catalog.is_reconcilable("signal_service_down_failure") is True
		assert catalog.is_reconcilable("signal_interaction_unrendered_purged_failure") is False

	def test_politica_desde_yaml(self):
		from red_pill.metabolism.signal_profiles import load_catalog

		policy = load_catalog(force=True).reconcile_policy()
		assert policy["absences"] == 2
		assert policy["grace_hours"] == 24
		assert Path("configs/signals/signal_profiles.yaml").exists()


class TestIntegracion:
	def test_borra_solo_lo_del_auditor_contra_qdrant_en_memoria(self, memory_manager, tmp_path):
		memory_manager.storage.ensure_collection("signal_memories")
		memory_manager.inject_signal("signal_test_failure", intensity=6.0, signal_type="pain", source="SentinelAuditor")
		memory_manager.inject_signal("jobs_frustrated", intensity=5.0, signal_type="pain", source="JobMonitor")
		policy = {"report_only": False, "absences": 1}
		reconcile(_round(), memory_manager, policy=policy, state_dir=tmp_path)
		assert memory_manager.has_signal("signal_test_failure") is False
		assert memory_manager.has_signal("jobs_frustrated") is True
