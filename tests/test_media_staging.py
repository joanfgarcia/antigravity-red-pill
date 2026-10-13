"""TST-MEDIA-003: staging y promoción (RFC-HARNESS-004 §8.2, F4)."""

from __future__ import annotations

import pytest

from red_pill.core import media_staging


def _stg(monkeypatch, tmp_path):
	monkeypatch.setenv("RP_MEDIA_STAGING", str(tmp_path / "stg"))


def test_default_root_is_tmp(monkeypatch):
	monkeypatch.delenv("RP_MEDIA_STAGING", raising=False)
	monkeypatch.delenv("RP_TMP_DIR", raising=False)
	assert str(media_staging.staging_root()).endswith("tmp/red-pill/media/staging")


def test_root_from_tmp_dir(monkeypatch, tmp_path):
	monkeypatch.delenv("RP_MEDIA_STAGING", raising=False)
	monkeypatch.setenv("RP_TMP_DIR", str(tmp_path / "t"))
	assert media_staging.staging_root() == tmp_path / "t" / "red-pill" / "media" / "staging"


def test_root_from_env(monkeypatch, tmp_path):
	monkeypatch.setenv("RP_MEDIA_STAGING", str(tmp_path / "s"))
	assert media_staging.staging_root() == tmp_path / "s"


def test_order_dir_creates(monkeypatch, tmp_path):
	_stg(monkeypatch, tmp_path)
	assert media_staging.order_dir("enc1", create=True).is_dir()


def test_list_artifacts(monkeypatch, tmp_path):
	_stg(monkeypatch, tmp_path)
	od = media_staging.order_dir("enc1", create=True)
	(od / "a.png").write_bytes(b"a")
	(od / "metrics.jsonl").write_text("{}")
	assert [p.name for p in media_staging.list_artifacts("enc1")] == ["a.png"]


def test_promote_single_copies(monkeypatch, tmp_path):
	_stg(monkeypatch, tmp_path)
	od = media_staging.order_dir("enc1", create=True)
	(od / "a.png").write_bytes(b"img")
	dest = media_staging.promote("enc1", str(tmp_path / "final"))
	assert dest == tmp_path / "final" / "a.png"
	assert dest.read_bytes() == b"img"
	assert (od / "a.png").exists()  # copia, no mueve


def test_promote_ambiguous_requires_name(monkeypatch, tmp_path):
	_stg(monkeypatch, tmp_path)
	od = media_staging.order_dir("enc1", create=True)
	(od / "a.png").write_bytes(b"a")
	(od / "b.png").write_bytes(b"b")
	with pytest.raises(ValueError):
		media_staging.promote("enc1", str(tmp_path / "final"))
	dest = media_staging.promote("enc1", str(tmp_path / "final"), name="b.png")
	assert dest.name == "b.png" and dest.read_bytes() == b"b"


def test_promote_move(monkeypatch, tmp_path):
	_stg(monkeypatch, tmp_path)
	od = media_staging.order_dir("enc1", create=True)
	(od / "a.png").write_bytes(b"a")
	media_staging.promote("enc1", str(tmp_path / "final"), move=True)
	assert not (od / "a.png").exists()
	assert (tmp_path / "final" / "a.png").exists()


def test_promote_missing_staging(monkeypatch, tmp_path):
	_stg(monkeypatch, tmp_path)
	with pytest.raises(FileNotFoundError):
		media_staging.promote("nope", str(tmp_path / "final"))


def test_cli_media_commands(monkeypatch, tmp_path, capsys):
	import argparse

	from red_pill.core import media_router
	from red_pill.media_cli import handle_media

	elenco = tmp_path / "media_profiles.yaml"
	elenco.write_text(
		"media_profiles:\n  m: { constraints: { dim_multiple: 16 }, adapters: [snap_dims] }\nmedia_roles:\n  t: [m]\n",
		encoding="utf-8",
	)
	monkeypatch.setattr(media_router, "_MEDIA_SINGLETON", media_router.MediaProfiles(path=elenco))

	handle_media(argparse.Namespace(media_cmd="resolve", task="t", model=None))
	assert capsys.readouterr().out.strip() == "m"

	handle_media(argparse.Namespace(media_cmd="adapt", model="m", width=1920, height=1080))
	assert "1088" in capsys.readouterr().out
