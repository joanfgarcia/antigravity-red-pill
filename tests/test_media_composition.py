"""TST-MEDIA-008: eje de composición en el media_router — gate_composition + política compatible/strict.

Cubre el adapter `gate_composition` (dato del elenco) y la política `compatible` (fail-soft: warning) /
`strict` (error limpio). El vocabulario NO vive en el router: sale de `composition` del perfil.
"""

from __future__ import annotations

import pytest

from red_pill.core.media_router import MediaCapabilityError, MediaProfiles, _adapter_gate_composition

ELENCO = """
media_profiles:
  flux2_klein:
    modality: image
    task: text2image
    pipeline: Flux2KleinPipeline
    backend: diffusers
    capabilities: ["concept"]
    not_capable_for: []
    priority: 1
    constraints: { dim_multiple: 8 }
    adapters: ["snap_dims", "gate_composition"]
    composition: [reference_image, multi_reference, inpaint, mask, strength]
    composition_pipelines: { inpaint: Flux2KleinInpaintPipeline }
  bonsai_ternary:
    modality: image
    task: text2image
    pipeline: GpuPipeline
    backend: bonsai
    capabilities: ["concept"]
    not_capable_for: []
    priority: 3
    constraints: { dim_multiple: 32 }
    adapters: ["gate_composition"]
    composition: []
media_roles:
  concept: [flux2_klein, bonsai_ternary]
"""


def _profiles(tmp_path) -> MediaProfiles:
	path = tmp_path / "media_profiles.yaml"
	path.write_text(ELENCO, encoding="utf-8")
	return MediaProfiles(path=path)


def test_compatible_keep_supported_drop_unsupported(tmp_path):
	p = _profiles(tmp_path)
	r = p.validate(
		{"model": "flux2_klein", "width": 768, "height": 768,
		 "composition": {"reference_image": "a.png", "img2img": "b.png"}},
		policy="compatible",
	)
	assert r["status"] == "adapted"
	assert r["adapted"]["composition"] == {"reference_image": "a.png"}  # img2img descartado
	assert any("img2img" in w for w in r["warnings"])


def test_strict_raises_error(tmp_path):
	p = _profiles(tmp_path)
	r = p.validate(
		{"model": "flux2_klein", "width": 768, "height": 768, "composition": {"img2img": "b.png"}},
		policy="strict",
	)
	assert r["status"] == "error"
	assert any("strict" in e for e in r["errors"])


def test_model_without_composition_drops_all(tmp_path):
	p = _profiles(tmp_path)
	r = p.validate(
		{"model": "bonsai_ternary", "width": 768, "height": 768, "composition": {"reference_image": "a.png"}},
		policy="compatible",
	)
	assert r["status"] == "adapted"
	assert r["adapted"]["composition"] == {}
	assert any("reference_image" in w for w in r["warnings"])


def test_gate_is_noop_without_composition(tmp_path):
	p = _profiles(tmp_path)
	r = p.validate({"model": "flux2_klein", "width": 768, "height": 768})
	assert r["status"] == "ok"
	assert "composition" not in r["adapted"]


def test_gate_rejects_non_mapping():
	with pytest.raises(MediaCapabilityError):
		_adapter_gate_composition({"composition": [1, 2, 3]}, {"id": "x", "composition": []})


def test_transport_media_env_survives_sanitize(tmp_path, monkeypatch):
	"""H1: la composición viaja en `media_env` (no en `env`, que el sanitizador de script_job borra) y `_build_env`
	la aplica DESPUÉS del sanitizado → llega al hijo."""
	from red_pill.core import media_router
	from red_pill.jobs.drivers import script
	from red_pill.jobs.drivers.base import sanitize_job_env
	from red_pill.jobs.drivers.media_hook import validate_media_payload

	path = tmp_path / "media_profiles.yaml"
	path.write_text(ELENCO, encoding="utf-8")
	monkeypatch.setattr(media_router, "_MEDIA_SINGLETON", MediaProfiles(path=path))

	payload = {
		"step_command": "x",
		"media": {"model": "flux2_klein", "width": 768, "height": 768,
		          "composition": {"reference_image": "a.png", "img2img": "b.png"}},
	}
	validate_media_payload(payload)
	# 1) El env media va en su clave, NO en `payload['env']`.
	assert "RP_MEDIA_MODEL" not in (payload.get("env") or {})
	assert payload["media_env"]["RP_MEDIA_MODEL"] == "flux2_klein"
	assert payload["media_env"]["RP_MEDIA_WIDTH"] == "768"
	assert "reference_image" in payload["media_env"]["RP_MEDIA_COMPOSITION"]
	assert payload["media_env"]["RP_MEDIA_COMPOSITION_POLICY"] in ("compatible", "strict")
	# 2) El sanitizador borraría los RP_* (por eso el transporte va aparte).
	assert sanitize_job_env({"RP_MEDIA_MODEL": "x", "KEEP": "y"}) == {"KEEP": "y"}
	# 3) `_build_env` los aplica después del sanitizado → llegan al proceso hijo.
	driver = object.__new__(script.ScriptJobDriver)
	driver.job_id = "t"
	env = driver._build_env(payload, cwd=str(tmp_path))
	assert env["RP_MEDIA_MODEL"] == "flux2_klein"
	assert env["RP_MEDIA_WIDTH"] == "768"


def test_parity_router_vs_harness(tmp_path, monkeypatch):
	"""Paridad: el harness (espejo) y el router filtran igual la composición para el mismo modelo/elenco."""
	import importlib.util
	from pathlib import Path

	path = tmp_path / "media_profiles.yaml"
	path.write_text(ELENCO, encoding="utf-8")
	monkeypatch.setenv("REDPILL_MEDIA_PROFILES", str(path))
	monkeypatch.setenv("RP_MEDIA_COMPOSITION_POLICY", "compatible")

	bench_path = Path(__file__).resolve().parents[1] / "scripts" / "imagegen" / "bench_imagegen.py"
	spec = importlib.util.spec_from_file_location("bench_imagegen_parity", bench_path)
	harness = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(harness)

	model = harness.MODELS["flux2_klein"]
	meta = {"reference_image": "a.png", "img2img": "b.png"}
	kept, hwarns = harness.apply_composition(dict(meta), model)
	rparams, rwarns = _adapter_gate_composition(
		{"composition": dict(meta)}, {**model, "_policy": "compatible"}
	)
	assert rparams["composition"] == kept == {"reference_image": "a.png"}
	assert len(rwarns) == len(hwarns) == 1
