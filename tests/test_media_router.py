"""TST-MEDIA-001: media_router — router por tarea y adaptadores (docs/CORE/MEDIA_MODELS.md F1)."""

from __future__ import annotations

import pytest

from red_pill.core.media_router import (
	ADAPTERS,
	MediaCapabilityError,
	MediaProfileError,
	MediaProfiles,
)

ELENCO = """
media_profiles:
  flux2_klein:
    modality: image
    task: text2image
    capabilities: ["photorealism", "concept", "landscape", "fast"]
    not_capable_for: []
    priority: 1
    constraints: { dim_multiple: 8 }
    adapters: ["snap_dims"]
    vram_footprint: { peak_mb: 2456 }
  zimage_turbo:
    modality: image
    task: text2image
    capabilities: ["typography", "product", "photorealism"]
    not_capable_for: []
    priority: 2
    constraints: { dim_multiple: 16, max_pixels: 4194304, max_vram_mb: 6500 }
    adapters: ["snap_dims", "reject_oversize"]
    vram_footprint: { peak_mb: 2448 }
  bonsai_ternary:
    modality: image
    task: text2image
    capabilities: ["photorealism", "illustration", "ternary"]
    not_capable_for: []
    priority: 3
    constraints: { dim_multiple: 32, max_pixels: 1600000 }
    adapters: ["snap_dims", "reject_oversize"]
    vram_footprint: { peak_mb: 6721 }
  moss_sfx:
    modality: audio
    task: sfx
    capabilities: ["foley"]
    not_capable_for: []
    priority: 1
    constraints: { max_vram_mb: 6400 }
    adapters: ["reject_oversize"]
    vram_footprint: { peak_mb: 7400 }
media_roles:
  typography:   [zimage_turbo]
  concept:      [flux2_klein, bonsai_ternary]
  photoreal:    [flux2_klein, zimage_turbo, bonsai_ternary]
  sfx:          [moss_sfx]
"""


def _profiles(tmp_path) -> MediaProfiles:
	path = tmp_path / "media_profiles.yaml"
	path.write_text(ELENCO, encoding="utf-8")
	return MediaProfiles(path=path)


def test_missing_file_raises(tmp_path):
	with pytest.raises(MediaProfileError):
		MediaProfiles(path=tmp_path / "nope.yaml").profiles()


def test_adapters_registry():
	assert {"snap_dims", "reject_oversize"} <= set(ADAPTERS)


def test_resolve_by_task(tmp_path):
	mp = _profiles(tmp_path)
	assert mp.resolve(task="typography") == "zimage_turbo"
	assert mp.resolve(task="concept") == "flux2_klein"
	assert mp.resolve(task="sfx") == "moss_sfx"


def test_resolve_by_model(tmp_path):
	mp = _profiles(tmp_path)
	assert mp.resolve(model="bonsai_ternary") == "bonsai_ternary"


def test_resolve_model_unknown_raises(tmp_path):
	with pytest.raises(MediaCapabilityError):
		_profiles(tmp_path).resolve(model="nope")


def test_resolve_requires_arg(tmp_path):
	with pytest.raises(MediaCapabilityError):
		_profiles(tmp_path).resolve()


def test_resolve_unknown_task_raises(tmp_path):
	with pytest.raises(MediaCapabilityError):
		_profiles(tmp_path).resolve(task="nope")


def test_not_capable_for_skips(tmp_path):
	path = tmp_path / "media_profiles.yaml"
	path.write_text(
		"media_profiles:\n  a: { capabilities: [x], not_capable_for: [x] }\n  b: { capabilities: [x] }\nmedia_roles:\n  x: [a, b]\n",
		encoding="utf-8",
	)
	assert MediaProfiles(path=path).resolve(task="x") == "b"


def test_not_capable_for_all_raises(tmp_path):
	path = tmp_path / "media_profiles.yaml"
	path.write_text(
		"media_profiles:\n  a: { capabilities: [x], not_capable_for: [x] }\nmedia_roles:\n  x: [a]\n",
		encoding="utf-8",
	)
	with pytest.raises(MediaCapabilityError):
		MediaProfiles(path=path).resolve(task="x")


def test_adapt_snap_1080_to_1088(tmp_path):
	adapted, warnings = _profiles(tmp_path).adapt("zimage_turbo", {"width": 1920, "height": 1080})
	assert adapted == {"width": 1920, "height": 1088}
	assert warnings and "1080→1088" in warnings[0]


def test_adapt_flux2_keeps_1080(tmp_path):
	adapted, warnings = _profiles(tmp_path).adapt("flux2_klein", {"width": 1920, "height": 1080})
	assert adapted == {"width": 1920, "height": 1080}
	assert warnings == []


def test_reject_oversize_pixels_bonsai(tmp_path):
	with pytest.raises(MediaCapabilityError):
		_profiles(tmp_path).adapt("bonsai_ternary", {"width": 1920, "height": 1088})


def test_reject_oversize_vram_moss(tmp_path):
	with pytest.raises(MediaCapabilityError):
		_profiles(tmp_path).adapt("moss_sfx", {})


def test_adapt_unknown_adapter_raises(tmp_path):
	path = tmp_path / "media_profiles.yaml"
	path.write_text(
		"media_profiles:\n  a: { adapters: [nope] }\n",
		encoding="utf-8",
	)
	with pytest.raises(MediaProfileError):
		MediaProfiles(path=path).adapt("a", {})


def test_validate_ok(tmp_path):
	res = _profiles(tmp_path).validate({"model": "flux2_klein", "width": 1920, "height": 1080})
	assert res["status"] == "ok"
	assert res["model"] == "flux2_klein"
	assert res["adapted"] == {"width": 1920, "height": 1080}
	assert res["warnings"] == [] and res["errors"] == []


def test_validate_adapted(tmp_path):
	res = _profiles(tmp_path).validate({"model": "zimage_turbo", "width": 1920, "height": 1080})
	assert res["status"] == "adapted"
	assert res["adapted"]["height"] == 1088
	assert res["warnings"]


def test_validate_error_task(tmp_path):
	res = _profiles(tmp_path).validate({"task": "nope"})
	assert res["status"] == "error"
	assert res["errors"]


def test_validate_error_oversize(tmp_path):
	res = _profiles(tmp_path).validate({"model": "bonsai_ternary", "width": 1920, "height": 1088})
	assert res["status"] == "error"
	assert res["model"] == "bonsai_ternary"
