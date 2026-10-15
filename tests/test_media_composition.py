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
