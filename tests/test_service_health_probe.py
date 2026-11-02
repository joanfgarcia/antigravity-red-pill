"""Semántica del health probe: un proxy de inferencia cargando un modelo no está
colgado, y el RSS se mide por procesos (no por el cgroup con su cache).

El sentinel sondeaba todos los daemons con 5 s de timeout y severidad 9. El
`redpill-llm.service` bloquea su hilo mientras carga un GGUF, así que cada ciclo
nocturno fabricaba un `hung_service` severidad 9 (señal de dolor falsa el
2026-11-02 06:03, justo al arrancar el sueño).

El aviso de memoria (`memory_bloat`) leía `MemoryCurrent`, que suma page cache y
picos de hijos transitorios: marcaba 500 MB con el daemon estable en ~343 MB.
"""

import os
import subprocess
from types import SimpleNamespace

from red_pill.metabolism.sentinel_plugins.check_duplicate_services import (
	HEALTH_TIMEOUT_S,
	LLM_HEALTH_TIMEOUT_S,
	MEMORY_LIMIT_MB,
	ServiceHealthCheck,
	_health_timeout,
	_hung_severity,
)


class TestHealthTimeout:
	def test_daemons_normales_usan_el_margen_corto(self):
		assert _health_timeout("redpill.service") == HEALTH_TIMEOUT_S
		assert _health_timeout("redpill-mcp.service") == HEALTH_TIMEOUT_S

	def test_el_proxy_de_inferencia_tiene_margen_de_carga(self):
		assert _health_timeout("redpill-llm.service") == LLM_HEALTH_TIMEOUT_S
		assert LLM_HEALTH_TIMEOUT_S > HEALTH_TIMEOUT_S


class TestHungSeverity:
	def test_un_daemon_inalcanzable_es_rojo(self):
		assert _hung_severity("redpill.service") >= 8.0

	def test_el_proxy_ocupado_no_es_rojo(self):
		"""Cargando modelo o infiriendo: amarillo, no cuelgue."""
		assert _hung_severity("redpill-llm.service") < 8.0


class TestMemoryMeter:
	def test_mide_los_procesos_no_el_cgroup(self, monkeypatch):
		check = ServiceHealthCheck()
		monkeypatch.setattr(check, "_unit_pids", lambda unit: [os.getpid()])
		mb = check._get_unit_rss_mb("redpill.service")
		assert 5 < mb < 4096

	def test_fallback_al_contador_del_cgroup(self, monkeypatch):
		check = ServiceHealthCheck()
		monkeypatch.setattr(check, "_unit_pids", lambda unit: [])
		monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="MemoryCurrent=104857600\n"))
		assert round(check._get_unit_rss_mb("redpill.service")) == 100

	def test_umbral_por_encima_del_ruido_del_cgroup(self):
		"""El umbral tiene que superar los ~500 MB que pica el cgroup sin bloat."""
		assert MEMORY_LIMIT_MB > 500
