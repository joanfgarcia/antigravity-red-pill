"""compat_image_studio.py — shim para image-studio/backend_gpu con torch>=2.10.

El `pipeline_gpu._load_gemlite_transformer` de Prism ML carga el transformer
gemlite con un hack por-capa que bajo torch>=2.10 revienta (asigna un Tensor a un
slot `Parameter`) y asume un registro de buffers distinto al de gemlite 0.6.x.
Sustituimos SÓLO esa función por una equivalente que intercambia las capas con el
ctor de gemlite 0.6 (que pre-registra los buffers) y carga el `state_dict` en
bloque, sin tocar el repo de terceros (clonado en $IMAGE_FORGE_HOME/image-studio).

Se aplica de forma idempotente antes de construir `GpuPipeline`.
"""

from __future__ import annotations

_GEMLITE_LAYER_KEYS = ("W_q", "bias", "scales", "zeros", "metadata", "orig_shape")


def apply(pipeline_gpu_module) -> bool:
	"""Monkeypatch idempotente de `_load_gemlite_transformer` (gemlite 0.6.x
	pre-registra W_q/scales/zeros/metadata/orig_shape/meta_scale como buffers)."""
	if getattr(pipeline_gpu_module, "_redpill_gemlite_compat2", False):
		return True
	if not hasattr(pipeline_gpu_module, "_load_gemlite_transformer"):
		return False
	pipeline_gpu_module._load_gemlite_transformer = _load_gemlite_transformer_fixed
	pipeline_gpu_module._redpill_gemlite_compat2 = True
	return True


def _load_gemlite_transformer_fixed(path, *, device="cuda:0"):
	"""Carga el transformer gemlite int2 sobre gemlite 0.6.x (buffers nativos).

	Flujo: construir Flux2Transformer2DModel e intercambiar cada nn.Linear con
	claves gemlite por un GemLiteLinearTriton (el ctor 0.6 pre-registra todos los
	buffers), luego un único `model.load_state_dict(state, strict=False)` carga
	W_q/scales/zeros/metadata/orig_shape. `strict=False` tolera `meta_scale`
	ausente en packs antiguos (queda en su default 0.0 = sin meta-escala).
	"""
	import json
	from pathlib import Path

	import torch
	from gemlite.core import DType, GemLiteLinearTriton, set_packing_bitwidth

	path = Path(path)
	cfg = json.loads((path / "config.json").read_text())
	qcfg = json.loads((path / "quantization_config.json").read_text())
	bits = int(qcfg.get("bits", 1))
	group_size = int(qcfg.get("group_size", 128))
	packing_bw = int(qcfg.get("packing_bitwidth", 8))

	set_packing_bitwidth(packing_bw)
	GemLiteLinearTriton.load_config(str(path / "gemlite_autotune.json"))

	from diffusers import Flux2Transformer2DModel

	model = Flux2Transformer2DModel.from_config(cfg).to(torch.bfloat16)
	state = torch.load(str(path / "state_dict.pt"), map_location="cpu")

	layer_fqns = {k.rpartition(".")[0] for k in state if k.rpartition(".")[2] in _GEMLITE_LAYER_KEYS and k.rpartition(".")[0]}
	n_swapped = 0
	for fqn in layer_fqns:
		parent_fqn, _, child_name = fqn.rpartition(".")
		parent = model.get_submodule(parent_fqn) if parent_fqn else model
		lin = getattr(parent, child_name)
		gl = GemLiteLinearTriton(
			W_nbits=bits,
			group_size=group_size,
			in_features=lin.in_features,
			out_features=lin.out_features,
			input_dtype=DType.FP16,
			output_dtype=DType.FP16,
		)
		setattr(parent, child_name, gl)
		n_swapped += 1

	missing, unexpected = model.load_state_dict(state, strict=False)
	# Sólo toleramos el buffer meta_scale ausente en packs antiguos; el resto es error real.
	hard_missing = [k for k in missing if not k.endswith("meta_scale")]
	if hard_missing:
		raise RuntimeError(f"missing keys tras swap gemlite: {hard_missing[:8]}")
	if unexpected:
		raise RuntimeError(f"unexpected keys: {unexpected[:8]}")

	model = model.to(torch.float16)
	for m in model.modules():
		if isinstance(m, GemLiteLinearTriton):
			object.__setattr__(m, "weight", None)
	model = model.to(device).eval()
	model._inference_dtype = torch.float16
	return model
