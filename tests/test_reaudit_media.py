"""Re-audit fixes: paridad de defaults, registro de backends, confinamiento y symlinks.

Cubre los flecos del segundo adversarial (SHARD-RV1/RV3, RA1/RA2/RA3, 38/39).
Carga los módulos standalone del harness (sin GPU) por importlib.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
IMAGE_PATH = SCRIPTS / "imagegen" / "gen_image.py"
CLI_PATH = SCRIPTS / "imagegen" / "gen_cli.py"
BENCH_PATH = SCRIPTS / "imagegen" / "bench_imagegen.py"
EXAMPLE = REPO / "examples" / "media_profiles.yaml.example"

sys.path.insert(0, str(SCRIPTS))


def _load(monkeypatch, name, path):
	monkeypatch.setenv("REDPILL_MEDIA_PROFILES", str(EXAMPLE))
	monkeypatch.setenv("REDPILL_RUNTIMES", str(REPO / "examples" / "runtimes.yaml.example"))
	spec = importlib.util.spec_from_file_location(name, path)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_media_console_env_paridad_paths(monkeypatch, tmp_path):
	"""`media_console_env` (standalone) == los defaults canónicos de `core/paths.py`."""
	import _config_common

	from red_pill.core import paths

	monkeypatch.setattr(_config_common, "config_dir", lambda: str(tmp_path))  # sin .env
	for k in ("IMAGE_FORGE_HOME", "REDPILL_IMAGE_MODELS_DIR", "RP_TMP_DIR", "RP_MEDIA_STAGING"):
		monkeypatch.delenv(k, raising=False)
	env = _config_common.media_console_env()
	assert env["IMAGE_FORGE_HOME"] == str(paths.get_forge_home("image"))
	assert env["REDPILL_IMAGE_MODELS_DIR"] == str(paths.get_image_models_dir())
	assert env["RP_TMP_DIR"] == str(paths.get_tmp_dir())


def test_console_out_dir_alineado_staging(monkeypatch, tmp_path):
	"""`console_out_dir()` cuelga del staging canónico (media_staging.staging_root())."""
	import _config_common

	from red_pill.core import media_staging

	monkeypatch.setattr(_config_common, "config_dir", lambda: str(tmp_path))
	monkeypatch.delenv("OUTDIR", raising=False)
	monkeypatch.delenv("RP_MEDIA_STAGING", raising=False)
	monkeypatch.setenv("RP_TMP_DIR", str(tmp_path / "t"))
	assert Path(_config_common.console_out_dir()).parent == media_staging.staging_root()


def test_gen_cli_ensure_image_falla_limpio(monkeypatch):
	"""Un modelo no-imagen (p.ej. audio) falla limpio; uno de imagen pasa."""
	m = _load(monkeypatch, "gen_cli_ra", CLI_PATH)
	with pytest.raises(SystemExit):
		m._ensure_image("__no_es_imagen__")
	assert m._ensure_image(next(iter(m.B.MODELS))) in m.B.MODELS


def test_snap_paridad_adapter_router(monkeypatch):
	"""`gen_cli._snap` == `media_router._adapter_snap_dims` (mismo ajuste de dims)."""
	from red_pill.core import media_router

	m = _load(monkeypatch, "gen_cli_snap", CLI_PATH)
	for mult in (8, 16, 32):
		for v in (100, 1024, 1080, 1920):
			_, _ = media_router._adapter_snap_dims({"width": v, "height": v}, {"constraints": {"dim_multiple": mult}})
			assert m._snap(v, mult) == media_router._adapter_snap_dims({"width": v}, {"constraints": {"dim_multiple": mult}})[0]["width"]


def test_gen_image_snap_paridad_adapter(monkeypatch):
	"""`gen_image._snap` == `media_router._adapter_snap_dims` (3ª copia, ahora guardada)."""
	from red_pill.core import media_router

	g = _load(monkeypatch, "gen_image_snap", IMAGE_PATH)
	for mult in (8, 16, 32):
		monkeypatch.setattr(g, "SNAP", mult)
		for v in (100, 1024, 1080, 1920):
			ref = media_router._adapter_snap_dims({"width": v}, {"constraints": {"dim_multiple": mult}})[0]["width"]
			assert g._snap(v) == ref


def test_gen_image_kind_desconocido(monkeypatch):
	g = _load(monkeypatch, "gen_image_k", IMAGE_PATH)
	with pytest.raises(RuntimeError):
		g._gen("nope", None, next(iter(g.MODELS)), "p", 1, 8, 8)


def test_bench_kind_desconocido(monkeypatch):
	b = _load(monkeypatch, "bench_k", BENCH_PATH)
	with pytest.raises(RuntimeError):
		b._generate("nope", None, next(iter(b.MODELS)), "p", 1, 8)


def test_gen_image_list_models_sin_staging(monkeypatch):
	"""`--list-models`/`--list-elements` NO exigen staging ni IMAGE_FORGE_HOME (RV1)."""
	for k in ("OUTDIR", "RP_MEDIA_STAGING", "RP_TMP_DIR", "IMAGE_FORGE_HOME"):
		monkeypatch.delenv(k, raising=False)
	g = _load(monkeypatch, "gen_image_lm", IMAGE_PATH)
	monkeypatch.setattr(sys, "argv", ["gen_image.py", "--list-models"])
	assert g.main() == 0


def test_gen_image_default_out_en_staging(monkeypatch, tmp_path):
	monkeypatch.setenv("RP_MEDIA_STAGING", str(tmp_path / "stg"))
	monkeypatch.delenv("OUTDIR", raising=False)
	g = _load(monkeypatch, "gen_image_do", IMAGE_PATH)
	assert g._default_out() == tmp_path / "stg" / "cli"


def test_gen_image_confine_out(monkeypatch, tmp_path):
	monkeypatch.setenv("RP_MEDIA_STAGING", str(tmp_path / "stg"))
	monkeypatch.delenv("OUTDIR", raising=False)
	g = _load(monkeypatch, "gen_image_cf", IMAGE_PATH)
	inside = tmp_path / "stg" / "enc"
	inside.mkdir(parents=True)
	assert g._confine_out(inside) == inside.resolve()
	with pytest.raises(SystemExit):
		g._confine_out(Path("/etc"))


def test_resolve_element_out(monkeypatch, tmp_path):
	"""`out` del payload se confina al staging; el `--out` del operador se respeta."""
	monkeypatch.setenv("RP_MEDIA_STAGING", str(tmp_path / "stg"))
	monkeypatch.delenv("OUTDIR", raising=False)
	g = _load(monkeypatch, "gen_image_ro", IMAGE_PATH)
	inside = tmp_path / "stg" / "enc"
	inside.mkdir(parents=True)
	assert g._resolve_element_out({"out": str(inside)}, None) == str(inside.resolve())
	with pytest.raises(SystemExit):
		g._resolve_element_out({"out": "/etc"}, None)
	assert g._resolve_element_out({}, "/tmp/op") == "/tmp/op"


def test_sanitize_job_env_bloquea_reservadas():
	"""El `env:` de una receta no puede pisar vars de política (staging/forges)."""
	from red_pill.jobs.drivers.base import sanitize_job_env

	out = sanitize_job_env({"RP_MEDIA_STAGING": "/", "OUTDIR": "/etc", "RP_TMP_DIR": "/", "FOO": "bar"})
	assert out == {"FOO": "bar"}


def test_order_dir_rechaza_symlink(monkeypatch, tmp_path):
	"""Un `order_dir` symlinkado no debe permitir listar/promocionar fuera del staging."""
	from red_pill.core import media_staging

	monkeypatch.setenv("RP_MEDIA_STAGING", str(tmp_path / "stg"))
	(tmp_path / "stg").mkdir()
	ext = tmp_path / "ext"
	ext.mkdir()
	(ext / "real.png").write_bytes(b"x")
	(tmp_path / "stg" / "enc_sym").symlink_to(ext)
	with pytest.raises(ValueError):
		media_staging.list_artifacts("enc_sym")


def test_media_staging_ignora_y_rechaza_symlinks(monkeypatch, tmp_path):
	from red_pill.core import media_staging

	monkeypatch.setenv("RP_MEDIA_STAGING", str(tmp_path / "stg"))
	od = media_staging.order_dir("enc1", create=True)
	external = tmp_path / "secret.txt"
	external.write_text("TOP_SECRET")
	(od / "leak.png").symlink_to(external)
	assert [p.name for p in media_staging.list_artifacts("enc1")] == []
	with pytest.raises(ValueError):
		media_staging.promote("enc1", str(tmp_path / "final"), name="leak.png")
