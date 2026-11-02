"""Semántica del health probe: un proxy de inferencia cargando un modelo no está
colgado.

El sentinel sondeaba todos los daemons con 5 s de timeout y severidad 9. El
`redpill-llm.service` bloquea su hilo mientras carga un GGUF, así que cada ciclo
nocturno fabricaba un `hung_service` severidad 9 (señal de dolor falsa el
2026-11-02 06:03, justo al arrancar el sueño).
"""

from red_pill.metabolism.sentinel_plugins.check_duplicate_services import (
	HEALTH_TIMEOUT_S,
	LLM_HEALTH_TIMEOUT_S,
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
