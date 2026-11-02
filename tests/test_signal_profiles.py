"""Taxonomía del dolor (AD-108): cinco clases, una ley por clase.

La escalada no puede depender de cuántas veces miramos: se calcula con la edad
real de la señal. Esta suite fija la ley (irritación nunca sube, necesidad se
queda en `error`, `sed` y `herida` cruzan un acantilado irreversible) y el
contrato del acuse (congela sin acantilado, solo silencia con acantilado).
"""

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from red_pill.core.paths import get_signal_profiles_path
from red_pill.memory import MemoryManager
from red_pill.metabolism.signal_profiles import (
	ACK_FREEZE,
	ACK_NONE,
	ACK_SILENCE,
	build_catalog,
	compute_intensity,
	load_catalog,
	stage_for,
)


@pytest.fixture(scope="module")
def catalog():
	return load_catalog(force=True)


class TestCatalogo:
	def test_el_yaml_canonico_se_carga(self, catalog):
		assert {"irritacion", "necesidad", "sed", "herida", "fallo"} <= set(catalog.classes)
		assert catalog.default_class == "necesidad"
		assert catalog.stages["warning"] == 4.0

	def test_el_yaml_apunta_al_repo(self):
		path = get_signal_profiles_path()
		assert path.exists(), path
		assert "signal_profiles.yaml" in path.name

	def test_fallback_no_diverge_del_yaml(self, catalog):
		"""Si el fichero desaparece se usa el fallback: no puede mentir distinto."""
		builtin = build_catalog()
		for name, cls in builtin.classes.items():
			real = catalog.classes[name]
			assert (cls.base, cls.slope_per_hour, cls.ceiling, cls.cliff_hours, cls.ack_mode) == (
				real.base,
				real.slope_per_hour,
				real.ceiling,
				real.cliff_hours,
				real.ack_mode,
			), name

	def test_senal_desconocida_cae_a_la_clase_por_defecto(self, catalog):
		assert catalog.class_for("senal_que_no_existe").name == "necesidad"

	def test_mapa_de_senales_reales(self, catalog):
		assert catalog.class_for("jobs_frustrated").name == "necesidad"
		assert catalog.class_for("chronicle_blocked_by_ide").name == "sed"
		assert catalog.class_for("service_down").name == "fallo"
		assert catalog.class_for("hung_service").name == "herida"
		assert catalog.class_for("sw_hub_coverage").name == "irritacion"


class TestLey:
	def test_irritacion_no_pasa_de_info(self, catalog):
		"""La picadura de mosquito no se convierte en hemorragia por esperar."""
		profile = catalog.classes["irritacion"]
		for age in (0.0, 24.0, 1000.0):
			intensity, stage = compute_intensity(profile, profile.base, age)
			assert stage == "info"
			assert intensity <= 3.0

	def test_necesidad_se_queda_en_error(self, catalog):
		"""Vejiga: molesta, llega a error... y se limpia. No hay no-retorno."""
		profile = catalog.classes["necesidad"]
		now = compute_intensity(profile, 2.5, 0.0)
		assert now == (2.5, "info")
		later = compute_intensity(profile, 2.5, 8.0)
		assert later[1] == "error"
		assert later[0] == 7.0
		forever = compute_intensity(profile, 2.5, 10_000.0)
		assert forever == (7.0, "error")

	def test_sed_cruza_el_acantilado_a_los_30_dias(self, catalog):
		"""Hambre/sed: escala despacio, pero al cruzar el tope no hay vuelta."""
		profile = catalog.classes["sed"]
		assert profile.cliff_hours == 720
		before = compute_intensity(profile, 2.5, 719.0)
		assert before[1] == "error"
		assert before[0] < 10.0
		after = compute_intensity(profile, 2.5, 720.0)
		assert after == (10.0, "system_failure")

	def test_herida_ya_duele_y_el_reloj_corre_en_minutos(self, catalog):
		profile = catalog.classes["herida"]
		start = compute_intensity(profile, profile.base, 0.0)
		assert start[1] == "error"
		assert compute_intensity(profile, profile.base, 0.5)[0] == 10.0

	def test_fallo_nace_en_el_maximo(self, catalog):
		profile = catalog.classes["fallo"]
		assert compute_intensity(profile, profile.base, 0.0) == (10.0, "system_failure")
		assert profile.ack_mode == ACK_NONE

	def test_un_evento_no_se_declara_mas_suave(self, catalog):
		"""`fallo` es un evento: aunque el productor pase 4.0, ya ocurrió y va a 10."""
		profile = catalog.classes["fallo"]
		assert compute_intensity(profile, 4.0, 0.0) == (10.0, "system_failure")

	def test_la_edad_negativa_no_resta(self, catalog):
		profile = catalog.classes["necesidad"]
		assert compute_intensity(profile, 5.0, -3.0)[0] == 5.0

	def test_etapas(self):
		assert stage_for(0.0) == "info"
		assert stage_for(3.9) == "info"
		assert stage_for(4.0) == "warning"
		assert stage_for(7.0) == "error"
		assert stage_for(10.0) == "system_failure"


def _mm_with_signal(payload=None):
	"""MemoryManager con el punto previo ya en el cortex (sin Qdrant real)."""
	mm = object.__new__(MemoryManager)
	mm.cfg = MagicMock(VECTOR_SIZE=4)
	mm.client = MagicMock()
	point = MagicMock()
	point.payload = payload
	mm.client.retrieve.return_value = [point] if payload is not None else []
	return mm


def _payload(name, hours_old=0.0, **extra):
	seen = datetime.now(timezone.utc) - timedelta(hours=hours_old)
	data = {
		"name": name,
		"intensity": 5.0,
		"created_at": seen.isoformat(),
		"first_seen_at": seen.isoformat(),
	}
	data.update(extra)
	return data


class TestInjectSignal:
	def test_el_reloj_es_tiempo_real_y_no_ticks(self):
		mm = _mm_with_signal(_payload("jobs_frustrated", hours_old=8.0))
		mm.inject_signal("jobs_frustrated", intensity=2.5, signal_type="pain", source="test")
		stored = mm.client.upsert.call_args.kwargs["points"][0].payload
		assert stored["intensity"] == 7.0  # 2.5 + 0.6*8 = 7.3, topado en el techo
		assert stored["stage"] == "error"
		assert stored["signal_class"] == "necesidad"
		assert stored["age_hours"] == pytest.approx(8.0, abs=0.1)

	def test_dos_ticks_seguidos_no_mueven_la_aguja(self):
		mm = _mm_with_signal(_payload("jobs_frustrated", hours_old=4.0))
		mm.inject_signal("jobs_frustrated", intensity=2.5, signal_type="pain", source="test")
		first = mm.client.upsert.call_args.kwargs["points"][0].payload["intensity"]
		mm.client.retrieve.return_value = [MagicMock(payload={"first_seen_at": _payload("jobs_frustrated", 4.0)["first_seen_at"], "intensity": first})]
		mm.inject_signal("jobs_frustrated", intensity=2.5, signal_type="pain", source="test")
		second = mm.client.upsert.call_args.kwargs["points"][0].payload["intensity"]
		assert second == pytest.approx(first, abs=0.2)

	def test_la_primera_vez_fija_first_seen(self):
		mm = _mm_with_signal(None)
		mm.inject_signal("hung_service", intensity=7.5, signal_type="pain", source="test")
		stored = mm.client.upsert.call_args.kwargs["points"][0].payload
		assert stored["first_seen_at"] == stored["created_at"]
		assert stored["signal_class"] == "herida"

	def test_acuse_congela_sin_acantilado(self):
		mm = _mm_with_signal(_payload("jobs_frustrated", hours_old=8.0, acked_at="x", acked_intensity=6.0))
		mm.inject_signal("jobs_frustrated", intensity=2.5, signal_type="pain", source="test")
		stored = mm.client.upsert.call_args.kwargs["points"][0].payload
		assert stored["intensity"] == 6.0
		assert stored["acknowledged"] is True

	def test_acuse_solo_silencia_con_acantilado(self):
		mm = _mm_with_signal(_payload("chronicle_blocked_by_ide", hours_old=100.0, acked_at="x", acked_intensity=3.0))
		mm.inject_signal("chronicle_blocked_by_ide", intensity=2.5, signal_type="pain", source="test")
		stored = mm.client.upsert.call_args.kwargs["points"][0].payload
		assert stored["intensity"] > 3.0  # el reloj no se detuvo
		assert stored["acknowledged"] is True

	def test_diagnostico_nuevo_rearma_el_acuse(self):
		viejo = hashlib.sha256("job-viejo".encode()).hexdigest()
		mm = _mm_with_signal(_payload("jobs_frustrated", hours_old=8.0, acked_at="x", acked_intensity=3.0, diagnosis_hash=viejo))
		mm.inject_signal("jobs_frustrated", intensity=2.5, signal_type="pain", source="test", diagnosis="job-nuevo")
		stored = mm.client.upsert.call_args.kwargs["points"][0].payload
		assert "acked_at" not in stored
		assert stored["intensity"] > 3.0

	def test_el_mensaje_volatil_no_rearma_el_acuse(self):
		"""El mensaje lleva edades y rutas que cambian solas: el acuse se queda."""
		viejo = hashlib.sha256("job-1".encode()).hexdigest()
		mm = _mm_with_signal(_payload("jobs_frustrated", hours_old=8.0, acked_at="x", acked_intensity=3.0, diagnosis_hash=viejo))
		mm.inject_signal(
			"jobs_frustrated",
			intensity=2.5,
			signal_type="pain",
			source="test",
			message="[PAIN] 1 job: abc 'x', 9h",
			diagnosis="job-1",
		)
		stored = mm.client.upsert.call_args.kwargs["points"][0].payload
		assert stored["acked_at"] == "x"
		assert stored["intensity"] == 3.0

	def test_el_evento_se_pierde_pero_se_ve(self):
		"""`fallo` no escala (ya ocurrió) y no se puede reconocer."""
		mm = _mm_with_signal(None)
		mm.inject_signal("service_down", intensity=10.0, signal_type="pain", source="test")
		stored = mm.client.upsert.call_args.kwargs["points"][0].payload
		assert stored["stage"] == "system_failure"


class TestAck:
	def test_ack_congela_la_intensidad(self):
		mm = _mm_with_signal({"name": "jobs_frustrated", "intensity": 5.5})
		result = mm.ack_signal("jobs_frustrated")
		assert result["status"] == "acked"
		assert result["ack_mode"] == ACK_FREEZE
		assert result["frozen_intensity"] == 5.5
		stored = mm.client.upsert.call_args.kwargs["points"][0].payload
		assert stored["acknowledged"] is True

	def test_ack_silencia_en_clases_con_acantilado(self):
		mm = _mm_with_signal({"name": "chronicle_blocked_by_ide", "intensity": 4.0})
		assert mm.ack_signal("chronicle_blocked_by_ide")["ack_mode"] == ACK_SILENCE

	def test_no_se_reconocen_eventos(self):
		mm = _mm_with_signal({"name": "service_down", "intensity": 10.0})
		assert mm.ack_signal("service_down")["status"] == "not_ackable"

	def test_ack_de_senal_inexistente(self):
		mm = _mm_with_signal(None)
		assert mm.ack_signal("fantasma")["status"] == "missing"
