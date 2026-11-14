"""El `peak_mb` del harness de imagen mide el DISPOSITIVO, no el asignador de torch.

Motivo (2026-11-14): `torch.cuda.max_memory_allocated()` sólo ve las asignaciones del
proceso actual. Con el backend `sd_cpp` el modelo corre en `sd-cli` (subproceso) → el
harness reportaba `peak_mb: 0.0` y el `vram_footprint` del elenco (lo que el router usa
para saber si un modelo cabe) era una estimación a ojo. `_DeviceVram` muestrea
`nvidia-smi` y reporta el incremento sobre la línea base tomada antes de cargar.

Tests sin GPU: el binario se inyecta (un script falso), así que la suite no necesita
nvidia-smi ni CUDA.
"""

import importlib.util
import stat
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "scripts" / "imagegen" / "bench_imagegen.py"
EXAMPLE = REPO / "examples" / "media_profiles.yaml.example"


def _load(monkeypatch):
	monkeypatch.setenv("REDPILL_MEDIA_PROFILES", str(EXAMPLE))
	spec = importlib.util.spec_from_file_location("bench_imagegen_vram_under_test", BENCH)
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def _fake_smi(tmp_path: Path, values, trailing_sleep: int = 30) -> Path:
	"""Script que imita a nvidia-smi: `-lms` → streaming; sin él → una sola lectura."""
	body = "#!/bin/sh\n" 'case "$*" in\n'
	body += "  *-lms*)\n"
	body += "    " + "".join(f"echo {v}; sleep 0.02; " for v in values) + f"sleep {trailing_sleep} ;;\n"
	body += f"  *) echo {values[0]} ;;\n"
	body += "esac\n"
	script = tmp_path / "fake-nvidia-smi"
	script.write_text(body, encoding="utf-8")
	script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
	return script


def test_parse_vram_mb(monkeypatch):
	m = _load(monkeypatch)
	assert m._parse_vram_mb("1234") == 1234.0
	assert m._parse_vram_mb(" 250 \n") == 250.0
	assert m._parse_vram_mb("[N/A]") is None
	assert m._parse_vram_mb("") is None
	assert m._parse_vram_mb(None) is None


def test_device_peak_es_el_incremento_del_dispositivo(monkeypatch, tmp_path):
	m = _load(monkeypatch)
	fake = _fake_smi(tmp_path, [10000, 10300, 10700])

	sampler = m._DeviceVram(binary=str(fake), interval_ms=20).prime()
	assert sampler.baseline_mb == 10000.0  # línea base = lectura única previa

	with sampler:
		time.sleep(0.25)  # deja que el stream emita la serie

	assert sampler.peak_abs_mb == 10700.0
	assert sampler.peak_delta_mb == pytest.approx(700.0)


def test_sin_binario_degrada_a_none(monkeypatch, tmp_path):
	m = _load(monkeypatch)
	missing = tmp_path / "no-existe-nvidia-smi"

	sampler = m._DeviceVram(binary=str(missing)).prime()
	assert sampler.baseline_mb is None

	with sampler:  # no revienta: simplemente no mide
		pass

	assert sampler.peak_abs_mb is None
	assert sampler.peak_delta_mb is None


def test_apagado_por_env(monkeypatch, tmp_path):
	m = _load(monkeypatch)
	fake = _fake_smi(tmp_path, [5000, 9000])
	monkeypatch.setenv("RP_VRAM_SAMPLER", "off")

	sampler = m._DeviceVram(binary=str(fake)).prime()
	assert sampler.baseline_mb is None
	with sampler:
		pass
	assert sampler.peak_delta_mb is None
	assert sampler._proc is None  # ni siquiera se lanza el subproceso
