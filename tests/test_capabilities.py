"""TST-CAP-001: capabilities — familias media activas + gate de siembra (docs/TECHNICAL/DECISION_LOG.md)."""

from __future__ import annotations

from pathlib import Path

from red_pill.core import capabilities


def _forge(root: Path, area: str, hf: bool) -> Path:
	home = root / f"{area}-forge"
	(home / "venv").mkdir(parents=True, exist_ok=True)
	if hf:
		(home / "hf-cache").mkdir(exist_ok=True)
	return home


def _isolate(monkeypatch, tmp_path, **homes):
	for area in ("image", "audio", "music"):
		monkeypatch.setenv(f"{area.upper()}_FORGE_HOME", str(homes.get(area, tmp_path / f"none-{area}")))


def test_no_forges_inactive(monkeypatch, tmp_path):
	_isolate(monkeypatch, tmp_path)
	assert capabilities.active_families() == []


def test_image_requires_hf_cache(monkeypatch, tmp_path):
	_isolate(monkeypatch, tmp_path, image=_forge(tmp_path, "image", hf=False))
	assert "image_gen" not in capabilities.active_families()
	_isolate(monkeypatch, tmp_path, image=_forge(tmp_path, "image", hf=True))
	assert "image_gen" in capabilities.active_families()


def test_all_active(monkeypatch, tmp_path):
	_isolate(
		monkeypatch,
		tmp_path,
		image=_forge(tmp_path, "image", hf=True),
		audio=_forge(tmp_path, "audio", hf=True),
		music=_forge(tmp_path, "music", hf=False),
	)
	assert set(capabilities.active_families()) == {"image_gen", "audio_gen", "music_gen"}


def test_enabled_for(monkeypatch, tmp_path):
	_isolate(monkeypatch, tmp_path, image=_forge(tmp_path, "image", hf=True))
	assert capabilities.enabled_for("image_gen") is True
	assert capabilities.enabled_for("audio_gen") is False
	assert capabilities.enabled_for("media") is True
	assert capabilities.enabled_for(None) is True


def test_skill_enabled_reads_frontmatter(monkeypatch, tmp_path):
	gated = tmp_path / "SKILL.md"
	gated.write_text("---\nname: x\ndescription: y\ncapability: image_gen\n---\n\n# x\n", encoding="utf-8")
	ungated = tmp_path / "other.md"
	ungated.write_text("---\nname: y\ndescription: z\n---\n\n# y\n", encoding="utf-8")

	_isolate(monkeypatch, tmp_path, image=_forge(tmp_path, "image", hf=True))
	assert capabilities.skill_enabled(gated) is True
	assert capabilities.skill_enabled(ungated) is True

	_isolate(monkeypatch, tmp_path)  # ninguna activa
	assert capabilities.skill_enabled(gated) is False
	assert capabilities.skill_enabled(ungated) is True
