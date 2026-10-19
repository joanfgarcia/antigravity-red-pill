"""`gen_cli.py` — launcher por elenco: resolución de modelo (por id o por rol) y snap.

No genera (eso carga modelos): solo ejercita las funciones puras de resolución.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "imagegen" / "gen_cli.py"
EXAMPLE = REPO / "examples" / "media_profiles.yaml.example"


def _load(monkeypatch):
	# El harness exige el env del elenco (falla limpio sin él): se lo damos.
	monkeypatch.setenv("REDPILL_MEDIA_PROFILES", str(EXAMPLE))
	monkeypatch.setenv("REDPILL_RUNTIMES", str(REPO / "examples" / "runtimes.yaml.example"))
	spec = importlib.util.spec_from_file_location("gen_cli_under_test", MOD)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_resolve_por_id(monkeypatch):
	m = _load(monkeypatch)
	data = {"media_profiles": {"a": {"backend": "diffusers"}}, "media_roles": {}}
	assert m._resolve_model(data, "a", None) == "a"


def test_resolve_por_rol_salta_not_capable(monkeypatch):
	m = _load(monkeypatch)
	data = {
		"media_profiles": {"a": {"not_capable_for": ["r"]}, "b": {}},
		"media_roles": {"r": ["a", "b"]},
	}
	assert m._resolve_model(data, None, "r") == "b"


def test_resolve_paridad_con_router(monkeypatch):
	"""`_resolve_model` es un espejo standalone: debe coincidir con el router (fuente única)."""
	import yaml

	from red_pill.core import media_router

	m = _load(monkeypatch)
	data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
	router = media_router.MediaProfiles(path=EXAMPLE)
	assert m._resolve_model(data, "flux2_klein", None) == router.resolve(model="flux2_klein")
	assert m._resolve_model(data, None, "photoreal") == router.resolve(task="photoreal")


def test_default_out_usa_staging(monkeypatch, tmp_path):
	m = _load(monkeypatch)
	monkeypatch.setenv("RP_MEDIA_STAGING", str(tmp_path / "stg"))
	monkeypatch.delenv("OUTDIR", raising=False)
	assert m._default_out() == str(tmp_path / "stg" / "cli")


def test_safe_stem_rechaza_traversal(monkeypatch):
	m = _load(monkeypatch)
	with pytest.raises(ValueError):
		m.G._safe_stem("../x", "name")
	with pytest.raises(ValueError):
		m.G._safe_stem("a/b", "tag")
	assert m.G._safe_stem("ok-name", "name") == "ok-name"


def test_resolve_rol_por_defecto(monkeypatch):
	m = _load(monkeypatch)
	data = {"media_profiles": {"x": {}}, "media_roles": {m.DEFAULT_ROLE: ["x"]}}
	assert m._resolve_model(data, None, None) == "x"


def test_modelo_desconocido_aborta(monkeypatch):
	m = _load(monkeypatch)
	with pytest.raises(SystemExit):
		m._resolve_model({"media_profiles": {}}, "no-existe", None)


def test_snap_multiplo(monkeypatch):
	m = _load(monkeypatch)
	assert m._snap(1080, 8) == 1080
	assert m._snap(1080, 16) == 1088
	assert m._snap(1000, 16) == 992
	assert m._snap(1024, 1) == 1024


def test_model_available_sd_cpp(tmp_path, monkeypatch):
	m = _load(monkeypatch)
	for k in ("diffusion_model", "text_encoder", "vae"):
		(tmp_path / f"{k}.bin").write_text("x")
	prof = {"backend": "sd_cpp", "sd_cpp": {k: str(tmp_path / f"{k}.bin") for k in ("diffusion_model", "text_encoder", "vae")}}
	assert m._model_available(prof) == (True, None)
	prof["sd_cpp"]["vae"] = str(tmp_path / "no-existe.bin")
	ok, why = m._model_available(prof)
	assert ok is False and "vae" in why


def test_model_available_diffusers_sin_cache(monkeypatch):
	m = _load(monkeypatch)
	ok, _why = m._model_available({"backend": "diffusers", "weights": "org/no-existe-jamas-xyz-123"})
	assert ok is False


def test_list_models_rc0(monkeypatch, capsys):
	"""SHARD-PV-05: `--list-models` emite el array JSON del elenco sin exigir staging."""
	import json

	m = _load(monkeypatch)
	monkeypatch.setattr("sys.argv", ["gen_cli.py", "--list-models"])
	assert m.main() == 0
	payload = json.loads(capsys.readouterr().out)
	assert isinstance(payload, list) and any(e["model"] == "flux2_klein" for e in payload)


def test_gen_image_override_steps_guidance(monkeypatch):
	"""`gen_image._gen(steps=…, guidance=…)` pisa el sampler del elenco para esa llamada."""
	monkeypatch.setenv("REDPILL_MEDIA_PROFILES", str(EXAMPLE))
	monkeypatch.setenv("REDPILL_RUNTIMES", str(REPO / "examples" / "runtimes.yaml.example"))
	spec = importlib.util.spec_from_file_location("gen_image_under_test", REPO / "scripts" / "imagegen" / "gen_image.py")
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	captured: dict = {}
	monkeypatch.setattr(mod.BENCH, "generate", lambda kind, cfg, *a, **k: captured.update(cfg) or "IMG")
	assert mod._gen("sd_cpp", None, "flux3_klein", "p", 1, 512, 512, steps=4, guidance=0.5) == "IMG"
	assert captured["steps"] == 4 and captured["guidance"] == 0.5


def test_resolucion_sobre_max_pixels_falla_limpio(monkeypatch, tmp_path):
	"""Guard del CLI (espejo de `reject_oversize`): por encima de max_pixels → SystemExit limpio, no OOM."""
	m = _load(monkeypatch)
	monkeypatch.setenv("RP_MEDIA_STAGING", str(tmp_path / "stg"))
	monkeypatch.setattr("sys.argv", ["gen_cli.py", "--model", "flux3_klein", "--prompt", "x", "--width", "1920", "--height", "1088"])
	with pytest.raises(SystemExit) as ei:
		m.main()
	assert "max_pixels" in str(ei.value)
