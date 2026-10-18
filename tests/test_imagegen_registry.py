"""El harness de imagen deriva su registro del ELENCO de máquina, no de código.

Invariante (CONVENTIONS §10.8.2 "data over branches"): `scripts/imagegen/
bench_imagegen.py` no contiene un dict `MODELS`; lo traduce de `media_profiles.yaml`.
Si esto se rompe, la "receta para añadir un modelo" vuelve a mentir.
"""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "scripts" / "imagegen" / "bench_imagegen.py"
EXAMPLE = REPO / "examples" / "media_profiles.yaml.example"


def _load(monkeypatch, profiles: Path):
	monkeypatch.setenv("REDPILL_MEDIA_PROFILES", str(profiles))
	spec = importlib.util.spec_from_file_location("bench_imagegen_under_test", BENCH)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_registry_reads_elencos(monkeypatch):
	m = _load(monkeypatch, EXAMPLE)
	assert set(m.MODELS) == {"flux2_klein", "zimage_turbo", "bonsai_ternary", "qwen_image_2_1_turbo", "flux3_klein"}

	f = m.MODELS["flux2_klein"]
	assert f["backend"] == "diffusers" and f["pipeline"] == "Flux2KleinPipeline"
	assert f["steps"] == 4 and f["guidance"] == 1.0 and f["license"] == "apache-2.0"

	assert m.MODELS["bonsai_ternary"]["backend_name"] == "bonsai-ternary-gemlite"

	q = m.MODELS["qwen_image_2_1_turbo"]
	assert q["backend"] == "sd_cpp" and q["steps"] == 8
	assert q["license"] == "qwen-research"
	assert q["sd_cpp"]["diffusion_model"].startswith("~/")
	assert q["sd_cpp"]["backend_assign"] == "te=cpu,diffusion=cuda0,vae=cuda0"

	f3 = m.MODELS["flux3_klein"]
	assert f3["backend"] == "sd_cpp" and f3["steps"] == 8
	assert f3["license"] == "flux-kommunity"
	assert f3["sd_cpp"]["diffusion_model"].startswith("~/")
	assert "vae_input_max_pixels=262144" in f3["sd_cpp"]["ref_image_args"]


def test_audio_models_excluded(monkeypatch):
	m = _load(monkeypatch, EXAMPLE)
	assert "kokoro_voice" not in m.MODELS and "moss_sfx" not in m.MODELS


def test_missing_elencos_fails_clean(monkeypatch, tmp_path):
	with pytest.raises(RuntimeError):
		_load(monkeypatch, tmp_path / "nope.yaml")
