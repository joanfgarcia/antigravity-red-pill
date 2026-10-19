"""Construcción del argv de `sd-cli`: text2img + edición/referencias.

`_sd_cpp_command` es pura (no ejecuta): permite verificar las flags sin cargar
modelos. El proyector de visión (`--llm_vision`) es **opcional y dirigido por el
dato**: se añade solo si el modelo declara `vision` en el elenco. Algunos modelos
(FLUX.3 klein) editan por referencia sin proyector (fail-soft).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "imagegen" / "bench_imagegen.py"
EXAMPLE = REPO / "examples" / "media_profiles.yaml.example"


def _load(monkeypatch):
	monkeypatch.setenv("REDPILL_MEDIA_PROFILES", str(EXAMPLE))
	monkeypatch.setenv("REDPILL_RUNTIMES", str(REPO / "examples" / "runtimes.yaml.example"))
	spec = importlib.util.spec_from_file_location("bench_cmd_under_test", MOD)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def _ctx(vision: bool = True) -> dict:
	ctx = {
		"binary": "/bin/sd-cli",
		"cfg": {"id": "m", "steps": 8, "guidance": 1.0, "sampler_method": "euler"},
		"sd": {"backend_assign": "te=cpu,diffusion=cuda0,vae=cuda0", "sigmas": "1.0,0.0", "extra_args": ["--flash-attn", "on"]},
		"paths": {"diffusion_model": "/d.gguf", "text_encoder": "/e.gguf", "vae": "/v.safetensors"},
	}
	if vision:
		ctx["paths"]["vision"] = "/mmproj.gguf"
	return ctx


def test_text2img_sin_vision_ni_edit(monkeypatch):
	m = _load(monkeypatch)
	cmd = m._sd_cpp_command(_ctx(vision=False), "p", 42, 1024, 1024, "/o.png")
	assert "--llm_vision" not in cmd and "-i" not in cmd and "--ref-image" not in cmd
	assert cmd[cmd.index("-W") + 1] == "1024" and cmd[cmd.index("-o") + 1] == "/o.png"


def test_edicion_con_vision_pasa_proyector(monkeypatch):
	m = _load(monkeypatch)
	cmd = m._sd_cpp_command(_ctx(), "edit it", 7, 1024, 1024, "/o.png", image="/in.png", strength=0.6)
	assert cmd[cmd.index("-i") + 1] == "/in.png"
	assert cmd[cmd.index("--strength") + 1] == "0.6"
	assert cmd[cmd.index("--llm_vision") + 1] == "/mmproj.gguf"


def test_edicion_sin_vision_no_fuerza_proyector(monkeypatch):
	m = _load(monkeypatch)
	cmd = m._sd_cpp_command(_ctx(vision=False), "edit", 7, 1024, 1024, "/o.png", image="/in.png")
	assert cmd[cmd.index("-i") + 1] == "/in.png"
	assert "--llm_vision" not in cmd


def test_referencias_repetibles(monkeypatch):
	m = _load(monkeypatch)
	cmd = m._sd_cpp_command(_ctx(), "compose", 1, 1024, 1024, "/o.png", ref_images=["/a.png", "/b.png"])
	assert cmd.count("--ref-image") == 2
	assert "--llm_vision" in cmd


def test_ref_image_args_solo_en_composicion(monkeypatch):
	m = _load(monkeypatch)
	ctx = _ctx(vision=False)
	ctx["sd"]["ref_image_args"] = {"vae_input_max_pixels": 262144, "resize_before_vae": True}
	assert "--ref-image-args" not in m._sd_cpp_command(ctx, "p", 1, 1024, 1024, "/o.png")
	cmd = m._sd_cpp_command(ctx, "c", 1, 1024, 1024, "/o.png", ref_images=["/a.png"])
	val = cmd[cmd.index("--ref-image-args") + 1]
	assert "vae_input_max_pixels=262144" in val and "resize_before_vae=true" in val


def test_mask_inpainting(monkeypatch):
	m = _load(monkeypatch)
	cmd = m._sd_cpp_command(_ctx(), "inpaint", 1, 1024, 1024, "/o.png", image="/in.png", mask="/m.png")
	assert cmd[cmd.index("--mask") + 1] == "/m.png"


def test_offload_condicional_por_pixeles(monkeypatch):
	m = _load(monkeypatch)
	ctx = _ctx(vision=False)
	ctx["sd"]["offload_over_pixels"] = 1500000
	assert "--offload-to-cpu" not in m._sd_cpp_command(ctx, "p", 1, 1024, 1024, "/o.png")
	assert "--offload-to-cpu" in m._sd_cpp_command(ctx, "p", 1, 1920, 1088, "/o.png")


def test_sigmas_solo_si_casan_los_pasos(monkeypatch):
	m = _load(monkeypatch)
	ctx = _ctx(vision=False)
	ctx["sd"]["sigmas"] = "1.0,0.9,0.7,0.4,0.0"  # 4 pasos
	assert "--sigmas" not in m._sd_cpp_command(ctx, "p", 1, 512, 512, "/o.png")      # steps=8 del _ctx ≠ 4
	ctx["cfg"]["steps"] = 4
	assert "--sigmas" in m._sd_cpp_command(ctx, "p", 1, 512, 512, "/o.png")          # steps=4 casa
	ctx["cfg"]["steps"] = 16
	assert "--sigmas" not in m._sd_cpp_command(ctx, "p", 1, 512, 512, "/o.png")      # steps=16 ≠ 4


def test_gen_sd_cpp_usa_cfg_override(monkeypatch):
	m = _load(monkeypatch)
	seen: dict = {}
	monkeypatch.setattr(m, "_sd_cpp_generate", lambda ctx, *a, **k: seen.update(ctx["cfg"]) or "IMG")
	cfg = {"id": "flux3_klein", "steps": 4, "guidance": 0.5}
	loaded_ctx = {"binary": "/bin/sd-cli", "cfg": {"id": "flux3_klein", "steps": 8}, "sd": {}, "paths": {}}
	assert m._gen_sd_cpp(cfg, loaded_ctx, "p", 1, 512, 512, {}) == "IMG"
	assert seen["steps"] == 4 and seen["guidance"] == 0.5
