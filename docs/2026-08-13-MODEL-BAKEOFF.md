# Bake-off de modelos de destilación — 2026-08-13

> De phi-4-mini a Llama-3.2-3B: qué partía, qué se evaluó, con qué nos quedamos
> y qué estamos obteniendo en producción. Acompaña al patch
> `2026-08-13-model-bakeoff.patch` (mismos cambios, formato git).
>
> **Host**: este documento es la memoria del patch de Titanium y describe SU
> máquina (RTX 3050 4GB, wheel llama-cpp-python, llama_32 como primario). La
> adaptación a este host (RTX 8GB compartida con entrenamiento, backend CLI
> llama.cpp, granite_8b primario) está en el CHANGELOG 7.18.0.

---

## 1. De qué partíamos

- **Destilador**: `phi_mini` (Microsoft Phi-4-mini 3.8B, Q4_K_M, 2.5GB GGUF) servido
  por el daemon (`MINION_PROFILE=phi_mini`), prompt `distiller_v3.txt`.
- **Ajuste de hardware justo**: RTX 3050 Laptop 4GB; phi ocupaba 2.5GB de pesos y
  a `n_ctx=8192` el KV + buffers (~3.6GB) hacían OOM silencioso → caída a CPU.
  Por eso se bajó a `n_ctx=4096` y luego a 6144.
- **Síntomas de calidad** (probes y en producción):
  - Deixis inestable: "Joan me dice que **he** abierto…", saltos de modo ("te digo"),
    deslices "Te dices".
  - Contaminación few-shot: el modelo pegaba fragmentos del prompt en los resúmenes
    ("cachear los embeddings en disco" salía en un brindis con vino).
  - Sesgo de idioma: phi etiquetaba texto en español como `en` (2/2 probes) → se
    añadió corrección mecánica `_correct_lang_label` en `distiller.py`.
  - Velocidad: 9-12s por probe; contienda VRAM con el daemon producía outputs
    corruptos (arrays numéricos como `relics_38: [1]`).
- **Objetivo**: encontrar un modelo equivalente a phi-4-instruct en síntesis que
  entre **100% en GPU** con **≥6K de contexto**, y sellar la voz del destilador.

## 2. El prompt: `distiller_v3_voice.txt` (Modo B)

Iteración sobre `distiller_v3.txt` durante la mañana:

1. **Contexto de identidad** en el system prompt (nombre del agente y del operador
   sustituidos por `{agent_name}`/`{operator_name}`) — igual que producción
   (`distiller.py:202` antepone identidad, `memory.py:514` formatea `USER:/ASSISTANT:`).
2. **Reglas DEIXIS** con ejemplos GOOD/BAD y **REFERENCE CONSISTENCY**: dos modos
   posibles, uno elegible: **MODE B** (operador en 3ª persona nombrada + yo/me:
   "Joan me dice que… le digo que…") o MODE A (2ª persona sin nombre). Nunca mezclar.
3. **Few-shot EXAMPLE 1** completo (caso CI/lint) para fijar formato JSON.
4. **Fidelity rules**: relics literales del DATA, prohibido el meta-análisis, idioma
   = idioma de la fuente, self-check de 5 puntos.
5. **Eliminación del vector de contaminación**: la lista de ejemplos de voz
   ("Le propongo cachear los embeddings en disco…") se quitó porque los modelos la
   incrustaban literal en resúmenes; se reforzó `category` ∈ {work, social}.
   Producción ya normaliza mecánicamente emoción/categoría inválidas
   (`distiller.py:296-303`), así que el prompt solo guía, no garantiza.
6. **Decisión de idioma**: español del fuente (la prueba de síntesis en inglés dio
   0/3 y errores semánticos; se descartó). `schemas_params.py:10` apunta por defecto
   al prompt nuevo.

## 3. Modelos evaluados (hardware: RTX 3050 Laptop 4GB, llama-cpp-python 0.3.32)

| Modelo | GGUF (Q4_K_M) | Resultado |
|---|---|---|
| **Phi-4-mini 3.8B** (baseline) | 2.5GB | 6144 ctx en GPU al límite (OOM a 8192 → CPU); deixis 1-2/3, contaminación, 9-12s/probe |
| **Gemma-3-4B** | 2.49GB | **Descartado**: KV SWA full-size; en GPU solo caben ~3072 tokens. FAIL a 6144 incluso con `kv_cache_type=q8_0/q4_0` |
| **Qwen3-4B-2507** | 2.50GB | **Descartado**: segfault CUDA con llama-cpp-python 0.3.32 (CPU OK); GGUF oficiales gated (401) |
| **OLMo-7B** | ~4.1GB | **Descartado a priori**: solo pesos > VRAM disponible; sin rango útil 1B-7B en la familia |
| **Llama-3.2-3B** ✅ | 2.02GB | **Ganador** — ver abajo |

Descargas en `~/.local/share/red-pill/models/`. Verificación de integridad del GGUF
de phi (sha256 vs HF) antes de sospechar del binario: los outputs corruptos eran
contienda VRAM, no el archivo.

## 4. Resultados del ganador: Llama-3.2-3B

**Fit** (medido, daemon parado):

| | phi_mini | llama_32 |
|---|---|---|
| Peso GGUF | 2.5GB | 2.0GB |
| Carga | ~2s | 1.0s |
| VRAM a 6144 | ~3041 MiB (borde) | ~3041 MiB **con ~1.2GB de margen** |
| Probes | 9-12s | 4-7s (~2x más rápido) |

**Cascade de contexto** (picos medidos con `n_gpu_layers=-1`):

| VRAM libre al boot | Tier | n_ctx | Pico |
|---|---|---|---|
| ≥ 3.5 GB | 8K | 8192 | 3345 MiB |
| 3.3–3.5 GB | 7K | 7168 | 3183 MiB |
| 3.0–3.3 GB | 6K | 6144 | 3041 MiB |
| < 3.0 GB | CPU (último recurso) | 16384 | — |

**Calidad** (prompt MODE B final, `scripts/model_battle.py`):

- Deixis: 3/3 probes correctas ("Joan me dice que **ha** abierto… le digo que…",
  "Joan me pregunta… le respondo…"), además de repetición limpia.
- Relics verbatim: 4/4, 2/2, 3/3 (literales).
- Contaminación: eliminada tras quitar la lista de ejemplos (en la versión con
  ejemplos, "le gusta el ambiente que pone" se colaba en los relics).
- Fidelidad both-sides (`distiller_fidelity.py`): base 1/3, **tuned 3/3** — empata
  con phi_mini tuned y con los 8B (granite/hermes) en la métrica oficial.
- Categoría: una salida inválida ("philosophy") en pruebas → producción la
  normaliza a `social`; la versión final del prompt la elimina.

## 5. Producción: qué se cambió

- **`model_profiles.yaml`** (fuera del repo, `~/.config/red-pill/`): perfil nuevo
  `llama_32` con cascade 8K→7K→6K; `phi_mini` GPU tier a `n_ctx: 6144`.
- **`model_registry.py`**: corregida la selección de tier — el código elegía con
  `free <= min` (invertido vs su docstring) y el `for-else` sin `break` forzaba el
  tier más bajo; ahora elige el tier más alto que cabe (`free >= min`), y si nada
  cabe, el más conservador.
- **systemd** (drop-in `redpill-llm.service.d/model-profile.conf`):
  `MINION_PROFILE=llama_32` (phi queda documentado como fallback).
- Harness de batalla añadido al repo: `scripts/model_battle.py`.
- Benchmarks: `docs/BENCHMARKS/DISTILLER_FIDELITY.md` con llama_32; quedan los
  nuevos `DISTILLER_BAKEOFF_PHI.*` / `DISTILLER_FIDELITY_PHI.*` de la mañana.

## 6. Resultados en producción (ciclo de sueño forzado, 12:41 →)

- ~814 engramas registrados en las primeras 2h10m; ritmo sostenido **~20.7
  engramas/min** (~1240/h) una vez caliente (8K → batches más grandes).
- **546→616+ engramas en Qdrant** (work 52k+, social ~1k, 52% fragmentos raw por
  diseño — cascade single-survivor; 48% destilados v3).
- Idioma: español 94% (6% en — MODE B correcto, fuentes en inglés); `lang`
  corregido mecánicamente cuando el modelo etiqueta mal.
- Deixis en muestra: 1 desliz aislado ("Me explicaste", 2ª persona) en ~10 engramas
  (phi: 1-2/3 en probes) → refuerzo opcional futuro: BAD example con verbo 2ª pers.
- Emociones/categoría saneadas por la taxonomía V3 (normaliza fuera-de-taxonomía);
  relics verbatim presentes; texture ~99% de los destilados.
- ETA: consolidación termina con el drain del buffer vivo (esta conversación);
  fases CPU 2-10 (~40-70 min) → fin del sueño ~15:30-16:30; Chronicle tras él
  (~10-30 min).

## 7. Archivos del patch

| Archivo | Cambio |
|---|---|
| `src/red_pill/metabolism/prompts/distiller_v3_voice.txt` | NUEVO — prompt MODE B final |
| `src/red_pill/core/model_registry.py` | Fix selección vram_tiers (cascade 8K/7K/6K) |
| `src/red_pill/metabolism/schemas_params.py` | Default prompt_file → distiller_v3_voice.txt |
| `src/red_pill/metabolism/distiller.py` | Corrección mecánica de idioma (mañana) |
| `scripts/distiller_bakeoff.py` / `distiller_fidelity.py` | Registro de phi_mini y llama_32 |
| `scripts/model_battle.py` | NUEVO — harness de batalla |
| `docs/BENCHMARKS/DISTILLER_FIDELITY.md` | Resultados llama_32 |
| `docs/BENCHMARKS/DISTILLER_BAKEOFF_PHI.*`, `DISTILLER_FIDELITY_PHI.*` | NUEVOS — benchmarks phi (mañana) |
| `docs/2026-08-13-MODEL-BAKEOFF.md` | Este documento |

Fuera del patch (máquinas, no versionables):
- `~/.config/red-pill/model_profiles.yaml`: perfil `llama_32` (cascade) + phi a 6144.
- `~/.config/systemd/user/redpill-llm.service.d/model-profile.conf`:
  `MINION_PROFILE=llama_32`.
- `~/.local/share/red-pill/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf` (2.02GB).

## Anexo A — `~/.config/red-pill/model_profiles.yaml` (verbatim, cambios de hoy)

Perfil `phi_mini` con el tier GPU ajustado de 8192 → 6144:

```yaml
  phi_mini:
    model_path: "models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf"
    binary_type: "gguf"
    hf_model_repo_id: "bartowski/microsoft_Phi-4-mini-instruct-GGUF"
    device_fallback: ["gpu", "cpu"]
    cpu_n_ctx: 16384
    temperature: 0.3
    max_tokens: 4096
    use_mmap: false
    capabilities: ["distillation", "logic", "emotional_intelligence", "deep"]
    hardware_affinity:
      n_ctx: 16384
      vram_tiers:
        # 2.5GB modelo + KV. Tier GPU solo con la tarjeta esencialmente libre.
        # RTX 3050 Laptop 4GB: n_ctx=8192 no cabe (KV+buffers ~3.6GB -> OOM
        # al crear llama_context y fallback silencioso a CPU). 4096 sí cabe.
        - min_free_gb: 1.5
          n_gpu_layers: 0
          n_ctx: 16384
        - min_free_gb: 3.2
          n_gpu_layers: -1
          n_ctx: 6144
```

Perfil nuevo `llama_32` (distiller principal) con cascade de contexto 8K→7K→6K:

```yaml
  # ── Distiller principal (2026-08-13): Llama-3.2-3B (Meta, Llama-3.2 license).
  # Ganó la bake-off contra phi-4-mini: 2.0GB GGUF, GPU completa, probes 4-7s,
  # deixis MODE B 3/3, relics verbatim, fidelidad tuned 3/3 both-sides.
  # Cascade de contexto (picos medidos 2026-08-13, RTX 3050 4GB):
  #   8K=3345 MiB | 7K=3183 MiB | 6K=3041 MiB — nunca menos de 6K en GPU;
  #   CPU (16K) solo de último recurso si ni 6K cabe.
  llama_32:
    model_path: "models/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
    binary_type: "gguf"
    hf_model_repo_id: "bartowski/Llama-3.2-3B-Instruct-GGUF"
    device_fallback: ["gpu", "cpu"]
    cpu_n_ctx: 16384
    temperature: 0.3
    max_tokens: 4096
    use_mmap: false
    capabilities: ["distillation", "logic", "emotional_intelligence"]
    hardware_affinity:
      n_ctx: 16384
      vram_tiers:
        - min_free_gb: 1.5
          n_gpu_layers: 0
          n_ctx: 16384
        - min_free_gb: 3.0
          n_gpu_layers: -1
          n_ctx: 6144
        - min_free_gb: 3.3
          n_gpu_layers: -1
          n_ctx: 7168
        - min_free_gb: 3.5
          n_gpu_layers: -1
          n_ctx: 8192
```

## Anexo B — systemd drop-in (verbatim)

`~/.config/systemd/user/redpill-llm.service.d/model-profile.conf`:

```ini
[Service]
# AD-023→LLAMA32: llama_32 distiller — Llama-3.2-3B Q4 completo en GPU.
# Ganó la bake-off 2026-08-13 vs phi-4-mini (deixis MODE B 3/3, relics
# verbatim, fidelidad tuned 3/3, ~2x más rápido, 2.0GB con margen VRAM).
# Volver a phi_mini si llama falla en el sleep (fallback documentado).
Environment=MINION_PROFILE=llama_32
```

## Anexo C — GGUF descargado (no incluido en el patch)

- `~/.local/share/red-pill/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf` (2.02GB)
  — fuente: `bartowski/Llama-3.2-3B-Instruct-GGUF` (HF público).
- Descartados (también en `models/`): `google_gemma-3-4b-it-Q4_K_M.gguf`
  (2.49GB) y `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` (2.50GB).
