"""TST-MEDIA-002: hook del bloque `media:` en el ensamblado (RFC-HARNESS-004 §8, F2)."""

from __future__ import annotations

import os

import pytest

from red_pill.core import media_router
from red_pill.core.media_router import MediaProfiles

ELENCO = """
media_profiles:
  flux2_klein:
    capabilities: ["concept"]
    constraints: { dim_multiple: 8 }
    adapters: ["snap_dims"]
  zimage_turbo:
    capabilities: ["typography"]
    constraints: { dim_multiple: 16, max_pixels: 4194304 }
    adapters: ["snap_dims", "reject_oversize"]
  bonsai_ternary:
    capabilities: ["illustration"]
    constraints: { dim_multiple: 32, max_pixels: 1600000 }
    adapters: ["snap_dims", "reject_oversize"]
media_roles:
  typography: [zimage_turbo]
  concept:    [flux2_klein]
  illustration: [bonsai_ternary]
"""


def _patch(monkeypatch, tmp_path):
	path = tmp_path / "media_profiles.yaml"
	path.write_text(ELENCO, encoding="utf-8")
	monkeypatch.setattr(media_router, "_MEDIA_SINGLETON", MediaProfiles(path=path))


def test_no_media_block_is_noop(monkeypatch, tmp_path):
	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.media_hook import validate_media_payload

	assert validate_media_payload({"step_command": "x"}) == []


def test_media_ok(monkeypatch, tmp_path):
	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.media_hook import validate_media_payload

	payload = {"media": {"model": "flux2_klein", "width": 1920, "height": 1080}}
	assert validate_media_payload(payload) == []
	assert payload["media_model"] == "flux2_klein"
	assert payload["media_adapted"] == {"width": 1920, "height": 1080}


def test_media_adapted_records_warning(monkeypatch, tmp_path):
	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.media_hook import validate_media_payload

	payload = {"media": {"model": "zimage_turbo", "width": 1920, "height": 1080}}
	warnings = validate_media_payload(payload)
	assert warnings and payload["media_warnings"] == warnings
	assert payload["media_adapted"]["height"] == 1088


def test_media_impossible_raises(monkeypatch, tmp_path):
	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.media_hook import MediaRecipeError, validate_media_payload

	with pytest.raises(MediaRecipeError):
		validate_media_payload({"media": {"model": "bonsai_ternary", "width": 1920, "height": 1088}})


def test_media_by_task(monkeypatch, tmp_path):
	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.media_hook import validate_media_payload

	payload = {"media": {"task": "typography", "width": 1024, "height": 1024}}
	validate_media_payload(payload)
	assert payload["media_model"] == "zimage_turbo"


def test_element_driver_validates_media(monkeypatch, tmp_path):
	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.element import ElementJobDriver

	payload = {"step_command": "x", "elements": [1], "media": {"task": "nope"}}
	with pytest.raises(ValueError):
		ElementJobDriver.validate(payload)


def test_script_driver_validates_media(monkeypatch, tmp_path):
	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.script import ScriptJobDriver

	with pytest.raises(ValueError):
		ScriptJobDriver.validate({"step_command": "x", "media": {"task": "nope"}})


def test_media_env_per_element_adapts(monkeypatch, tmp_path):
	import json

	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.media_hook import media_env_for_element

	payload = {"media": {"task": "concept", "width": 1920, "height": 1080}}
	# flux2 (÷8) conserva 1080; zimage (÷16) → 1088 + warning.
	env_flux = media_env_for_element(payload, {"model": "flux2_klein"})
	assert env_flux["RP_MEDIA_WIDTH"] == "1920" and env_flux["RP_MEDIA_HEIGHT"] == "1080"
	assert "RP_MEDIA_WARNINGS" not in env_flux

	env_zimg = media_env_for_element(payload, {"model": "zimage_turbo"})
	assert env_zimg["RP_MEDIA_HEIGHT"] == "1088"
	assert "1080→1088" in json.loads(env_zimg["RP_MEDIA_WARNINGS"])[0]


def test_media_env_per_element_impossible(monkeypatch, tmp_path):
	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.media_hook import media_env_for_element

	payload = {"media": {"task": "concept", "width": 1920, "height": 1080}}
	env = media_env_for_element(payload, {"model": "bonsai_ternary"})
	assert "RP_MEDIA_ERROR" in env
	assert "RP_MEDIA_WIDTH" not in env


def test_element_build_env_injects_media(monkeypatch, tmp_path):
	_patch(monkeypatch, tmp_path)
	from red_pill.jobs.drivers.element import ElementJobDriver

	driver = ElementJobDriver.__new__(ElementJobDriver)
	driver.job_id = "test"
	payload = {"media": {"task": "concept", "width": 1920, "height": 1080}}
	env = driver._build_env(payload, os.getcwd(), {"model": "zimage_turbo"}, 0)
	assert env["RP_MEDIA_HEIGHT"] == "1088"
	assert env["RP_MEDIA_MODEL"] == "zimage_turbo"
