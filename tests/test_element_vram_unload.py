"""`element_job` debe honrar `preflight.vram_unload` (paridad con `script_job`).

Bug 2026-10-14: la clave se ignoraba en silencio en `element_job` → con el LLM
residente ocupando la GPU, el gate `min_free_vram_mb` difería el job para siempre
(la receta pedía el unload y nadie lo hacía).
"""

from __future__ import annotations

from unittest.mock import patch

from red_pill.jobs.drivers.element import ElementJobDriver


def _driver() -> ElementJobDriver:
	driver = ElementJobDriver()
	driver.bind("job-test-0000", attempts=0, step_timeout_s=300)
	return driver


def test_preflight_vram_unload_llama_al_proxy():
	driver = _driver()
	calls: list[str] = []
	with patch.object(ElementJobDriver, "_request_vram_unload", staticmethod(lambda url: calls.append(url))):
		driver.preflight({"preflight": {"vram_unload": True}, "cwd": "/tmp"})
	assert calls == ["http://127.0.0.1:8760"]


def test_preflight_sin_vram_unload_no_llama_al_proxy():
	driver = _driver()
	calls: list[str] = []
	with patch.object(ElementJobDriver, "_request_vram_unload", staticmethod(lambda url: calls.append(url))):
		driver.preflight({"preflight": {}, "cwd": "/tmp"})
	assert calls == []
