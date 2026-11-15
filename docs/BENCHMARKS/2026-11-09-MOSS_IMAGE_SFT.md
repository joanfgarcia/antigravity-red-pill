# MOSS-Image-SFT — ficha y bench A/B (2026-11-09)

Modelo evaluado: [`unsloth/MOSS-Image-SFT-GGUF`](https://huggingface.co/unsloth/MOSS-Image-SFT-GGUF)
(quant de [OpenMOSS-Team/MOSS-Image-SFT](https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT)).

**Decisión: NO entra en el elenco.** No gana en ningún género de la matriz y
cuesta 12-35× más que los modelos ya clasificados. Los pesos se purgaron tras la
medición (~4,5 GB); esta ficha conserva lo aprendido y el snippet exacto para
re-evaluarlo si algún día cambia el hardware o aparece un build más rápido.

---

## 1. Qué es

| Campo | Valor |
|---|---|
| Arquitectura | DiT `moss_image`, 5.1 B (`dim 3072`, `ffn 8192`, `depth 42`, `channels 128`) |
| Encoder de texto | **Qwen3.5-9B** GGUF (el tokenizer oficial es obligatorio) |
| VAE | aparte, `vae/diffusion_pytorch_model.safetensors` (249 MB) del repo FP8 |
| Licencia | **apache-2.0** (comercial OK) |
| Defaults del autor | 50 pasos, CFG 3.0, shift 5, 1024² |
| Runtime | `sd_cpp` — el build local (`b13a482`) ya incluye `src/model/diffusion/moss_image.hpp` |
| VRAM pico medida | ~5,4 GB (DiT 4,5 GB + VAE; encoder en CPU) |

Ficheros usados (borrados tras el bench): `MOSS-Image-SFT-UD-Q6_K_XL.gguf` (4,2 GB),
`vae/diffusion_pytorch_model.safetensors`, `tokenizer/tokenizer.json` del repo
`unsloth/MOSS-Image-SFT-FP8`, y el encoder **ya presente** `Qwen3.5-9B-Q4_K_M.gguf`
(5,7 GB, `~/.local/share/red-pill/models/`).

## 2. Harness: lo que hubo que añadir

`sd-cli` **exige** `--tokenizer tokenizer.json` para esta arquitectura (no lo
infiere del `--llm`). El builder del harness no lo soportaba:

- `scripts/imagegen/bench_imagegen.py` → `_sd_cpp_command` pasa `--tokenizer` si el
  bloque `sd_cpp:` del elenco declara `tokenizer`; `_resolve_sd_cpp` y
  `_avail_sd_cpp` lo validan (fallo limpio si falta, nunca silencio).
- `--list-models` acepta `--models <csv>` (permite lanzar un A/B sobre un
  subconjunto sin tocar código).
- Tests: `tests/test_imagegen_sd_cpp_cmd.py::test_tokenizer_solo_si_el_elenco_lo_declara`.

La capacidad es genérica: cualquier DiT que necesite tokenizer externo la reutiliza.

## 3. Bench A/B — matriz fija `benchgenres.json` v1, seed 42, 1024²

`element_job` fail-soft, un step = un modelo, GPU liberada por preflight
(`vram_unload: true`). 30 imágenes, 0 fallos.

| modelo | retrato | tipogr. | ilustr. | paisaje | producto | concepto | media | vs flux2 | licencia |
|---|---|---|---|---|---|---|---|---|---|
| `flux2_klein` | 8 s | 7 s | 6 s | 6 s | 6 s | 6 s | **6,6 s** | 1× | apache-2.0 |
| `flux3_klein` | 17 s | 15 s | 15 s | 15 s | 15 s | 15 s | **15,2 s** | 2× | flux-kommunity |
| `zimage_turbo` | 21 s | 20 s | 20 s | 19 s | 19 s | 19 s | **19,6 s** | 3× | apache-2.0 |
| `qwen_image_2_1_turbo` | 36 s | 34 s | 30 s | 33 s | 31 s | 31 s | **32,5 s** | 5× | qwen-research (no comercial) |
| `moss_image_sft` | 221 s | 225 s | 229 s | 231 s | 233 s | 229 s | **228,0 s** | **35×** | apache-2.0 |

### Lectura por género

- **Tipografía — pierde.** `LISBOA` sale correcto, el subtítulo no: *"the City of
  siven Hills"* (por *seven*). También inventa un cartel ilegible en la ilustración
  (*"Linfer Boor Book Cho"*). Z-Image, Qwen y FLUX.3 escriben bien.
- **Retrato — empate con tic.** Detalle de piel/barba de los mejores del lote, pero
  **sobre-satura el rojo** y tira a HDR; flux2 y qwen quedan más creíbles.
- **Paisaje — su mejor terreno.** Atmósfera y god rays muy fotográficos, arriba del lote.
- **Concepto — bueno**, al nivel de flux2, algo más saturado.
- **Ilustración — flojo**: se come al gato del prompt y mete texto basura.
- **Producto — desobediente**: pedía la funda cerrada y abrió la caja con auriculares.

## 4. Curva de coste (barrido de pasos, mismo prompt y seed)

| pasos | medido | ajuste |
|---|---|---|
| 12 | 65,2 s | 64,0 s |
| 20 | 96,3 s | 97,6 s |
| 30 | 139,3 s | 139,5 s |
| 50 | 223,8 s | 223,4 s |

Ajuste lineal: **4,19 s/paso + 13,7 s fijos**. Los fijos son carga del GGUF +
encoder Qwen3.5-9B en CPU + decode del VAE ≈ **6,1 %** del total a 50 pasos. Es
decir: **el encoder en CPU no es el cuello** (asumir ~14 s de 228); el coste son
las 50 iteraciones × 2 ramas de CFG de un 5,1 B. Mover el encoder a GPU ahorraría
poco y no cabría (4,5 GB DiT + 5,7 GB encoder > 8 GB).

Calidad por pasos: **50 ≈ 30** (indistinguibles), 20 algo más suave, 12 pierde el
poro y plastifica la piel. La errata de tipografía es **idéntica a 20 y a 50**
pasos: límite del modelo, no presupuesto de pasos. Si se re-evaluara, 30 pasos es
el punto útil (139 s).

## 5. Veredicto

No sustituye a ninguno. No gana en ningún género, falla tipografía, y su único
activo —apache-2.0 con calidad alta— ya lo cubren `flux2_klein` (6,6 s) y
`zimage_turbo` (19,6 s). A 30 pasos seguiría siendo 21× flux2 y 4,3× qwen.

## 6. Para re-evaluarlo (snippet del elenco, sin usar)

Requiere volver a descargar ~4,5 GB (`--tokenizer` incluido, ya soportado por el
harness) y que este puesto tenga GPU con más VRAM o un build de `sd.cpp` más rápido:

```yaml
  moss_image_sft:
    modality: image
    task: text2image
    pipeline: sd_cpp
    backend: sd_cpp
    runtime: sd_cpp
    weights: "unsloth/MOSS-Image-SFT-GGUF"
    sampler: { steps: 30, guidance: 3.0, size: 1024, sampler: euler }   # 30 ≈ 50 en calidad
    vram_footprint: { peak_mb: 5400 }
    capabilities: ["photorealism", "concept", "landscape", "product"]
    not_capable_for: ["typography"]
    priority: 2
    constraints: { dim_multiple: 16, max_pixels: 4194304, max_vram_mb: 7600 }
    adapters: ["snap_dims", "reject_oversize", "gate_composition"]
    composition: []
    sd_cpp:
      diffusion_model: "~/opt/red-pill-custom-image-models/moss-image-sft/MOSS-Image-SFT-UD-Q6_K_XL.gguf"
      text_encoder: "~/opt/red-pill-custom-image-models/moss-image-sft/Qwen3.5-9B-Q4_K_M.gguf"
      vae: "~/opt/red-pill-custom-image-models/moss-image-sft/vae/diffusion_pytorch_model.safetensors"
      tokenizer: "~/opt/red-pill-custom-image-models/moss-image-sft/tokenizer/tokenizer.json"
      backend_assign: "te=cpu,diffusion=cuda0,vae=cuda0"
      extra_args: ["--flow-shift", "5", "--vae-tiling"]
    license: { id: "apache-2.0", commercial_ok: true, redistribution_ok: true, attribution_required: false, share_alike: false, source: "https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT" }
```

## 7. Reproducir

```bash
# 1) pesos (4,5 GB) → ~/opt/red-pill-custom-image-models/moss-image-sft
hf download unsloth/MOSS-Image-SFT-GGUF MOSS-Image-SFT-UD-Q6_K_XL.gguf --local-dir "$D"
hf download unsloth/MOSS-Image-SFT-FP8 vae/diffusion_pytorch_model.safetensors tokenizer/tokenizer.json --local-dir "$D"
ln -s ~/.local/share/red-pill/models/Qwen3.5-9B-Q4_K_M.gguf "$D/Qwen3.5-9B-Q4_K_M.gguf"
# 2) perfil en el elenco (§6) y A/B de 6 géneros
python scripts/imagegen/bench_imagegen.py --models moss_image_sft --out <dir>
```

Artefactos de la medición (PNG 30 + `metrics.jsonl` + contact sheets + barrido de
pasos) quedaron en el staging desechable `$RP_MEDIA_STAGING/moss-ab/` y
`…/moss-sweep/`.
