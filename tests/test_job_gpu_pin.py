"""Pin GPU de jobs (2026-10-05): VRAM-gate en element_job y device_fallback [gpu].

Cubre:
- `llm.device_fallback` → `RP_LLM_DEVICE_FALLBACK` (JSON) y su paso al payload del
  transporte Memento (nunca cascada a CPU).
- Gate `preflight.min_free_vram_mb` del element_job: residente en GPU → pasa sin
  coste; si no, exige VRAM libre suficiente; si no cabe → JobDeferred (no CPU).
- "insufficient free VRAM" cuenta como error de entorno (deferral), no de trabajo.
"""

from __future__ import annotations

import json

import pytest

from red_pill.jobs.drivers.base import JobDeferred, inject_llm_env
from red_pill.jobs.drivers.element import ElementJobDriver
from red_pill.memento.agentic.runner import _is_llm_connection_error


def test_inject_llm_env_device_fallback():
	env = inject_llm_env({"llm": {"task": "annotate", "model": "granite_8b", "device_fallback": ["gpu"]}})
	fallback = json.loads(env["RP_LLM_DEVICE_FALLBACK"])
	assert fallback == ["gpu"]
	assert env["RP_LLM_TASK"] == "annotate"
	assert env["RP_LLM_MODEL"] == "granite_8b"


def test_inject_llm_env_device_fallback_invalido():
	with pytest.raises(ValueError, match="device_fallback"):
		inject_llm_env({"llm": {"task": "annotate", "device_fallback": ["tpu"]}})


def test_is_llm_connection_error_gpu_llena():
	assert _is_llm_connection_error(RuntimeError("gpu: insufficient free VRAM"))


def test_llm_env_lee_device_fallback(monkeypatch):
	from red_pill.memento.agentic import runtime

	monkeypatch.setenv("RP_LLM_DEVICE_FALLBACK", '["gpu"]')
	assert runtime._llm_env()["device_fallback"] == ["gpu"]
	monkeypatch.setenv("RP_LLM_DEVICE_FALLBACK", "no-json")
	assert runtime._llm_env()["device_fallback"] == []


def _payload() -> dict:
	return {"llm": {"task": "annotate", "model": "granite_8b"}, "preflight": {"llm_required": True, "min_free_vram_mb": 7600}}


@pytest.fixture()
def driver_healthy(monkeypatch):
	monkeypatch.setattr(ElementJobDriver, "_llm_healthy", staticmethod(lambda port: True))
	return ElementJobDriver()


def test_preflight_pasa_si_residente_en_gpu(driver_healthy, monkeypatch):
	monkeypatch.setattr(ElementJobDriver, "_model_resident_on_gpu", staticmethod(lambda payload: True))

	from red_pill.core.vram_probe import VramProbe

	monkeypatch.setattr(VramProbe, "get_free_mb", staticmethod(lambda: 100))
	driver_healthy.preflight(_payload())  # no lanza: residente = coste 0


def test_preflight_difiere_si_no_cabe(driver_healthy, monkeypatch):
	monkeypatch.setattr(ElementJobDriver, "_model_resident_on_gpu", staticmethod(lambda payload: False))

	from red_pill.core.vram_probe import VramProbe

	monkeypatch.setattr(VramProbe, "get_free_mb", staticmethod(lambda: 1000))
	with pytest.raises(JobDeferred, match="sin fallback CPU"):
		driver_healthy.preflight(_payload())


def test_preflight_pasa_si_hay_vram_libre(driver_healthy, monkeypatch):
	monkeypatch.setattr(ElementJobDriver, "_model_resident_on_gpu", staticmethod(lambda payload: False))

	from red_pill.core.vram_probe import VramProbe

	monkeypatch.setattr(VramProbe, "get_free_mb", staticmethod(lambda: 8000))
	driver_healthy.preflight(_payload())
