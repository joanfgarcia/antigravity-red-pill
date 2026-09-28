# Distiller Selection — Choosing the Sleep-Cycle Model

The sleep cycle's distiller (`distill_engram` / `synthesize_hub` in `metabolism/sleep.py`)
is the single most quality-critical model in the Bünker: it decides what raw interactions
become permanent engrams, labels their `emotion`/`intensity`, and classifies `work` vs
`social`. A weak distiller poisons long-term memory (prompt-echo, English summaries of
Spanish talk, dramatized log noise). This document records how we pick it.

## The role's requirements

A good distiller must do four things at once:
1. **Strict JSON** — output only `{summary, emotion, intensity, category}`, parseable, no prose.
2. **Spanish fidelity** — the operator works in Spanish; summaries must stay in Spanish.
3. **Affective judgment** — sane `emotion`/`intensity`, and crucially *restraint*: log noise must be `neutral`/low-intensity so the culling filter drops it.
4. **Narrative grasp** — condense philosophy/relationship context without hallucinating.

A model tuned only for code (e.g. Qwen2.5-Coder) fails (3) and (4); the operator rejected it.

## Candidates

| Profile | Model | Why it's a candidate |
| :--- | :--- | :--- |
| `qwen35_9b` | Qwen3.5-9B Instruct | Generalist, 201 languages, large context. Engineering favorite (fits 8 GB, multilingual). |
| `beck_8b` | Beck-8B (Piaget finetune) | Qwen3-8B + LoRA on psychology/philosophy reasoning traces. Domain favorite for affective culling. |
| `piaget_8b` | Piaget-8B | The base psych/philo finetune Beck derives from; lighter alternative. |
| `hermes_8b` | Hermes-3-Llama-3.1-8B | Classic Llama arch (always loads). Fallback / control. |
| `samantha` | Samantha-Mistral-7B | Legacy distiller (2023). Baseline to beat. |

## Method — the bake-off harness

`scripts/distiller_bakeoff.py` runs an aptitude battery (one probe per requirement above)
against each downloaded candidate and scores outputs with **deterministic heuristics**:
`json_ok`, `has_keys`, `summary_lang` (ES/EN), `has_think_tags`, `echoes_prompt`
(reuses the production `_is_template_echo`), `emotion_valid`, `intensity_valid`, `latency_s`.

```
# GPU (all layers) — via the daemon's CUDA venv:
~/.local/share/red-pill/daemon/.venv/bin/python scripts/distiller_bakeoff.py \
    --models qwen35_9b,beck_8b,piaget_8b,hermes_8b,samantha --n-gpu-layers -1

# CPU only — via the project venv:
uv run python scripts/distiller_bakeoff.py --models ... --n-gpu-layers 0
```

Results land in `docs/BENCHMARKS/DISTILLER_BAKEOFF.md` (aggregate table + raw outputs) and
a sibling `.json`. Scores rank the field; **the operator confirms the winner** by reading the
raw summaries — heuristics catch format failures, not nuance.

### Execution modes — GPU, CPU, and hybrid (red-pill runs all three)
red-pill supports GPU and CPU **simultaneously** via partial offload, and the profiles'
`vram_tiers` encode exactly that: they pick `n_gpu_layers` from the *free* VRAM at launch.
- **All-GPU** (`--n-gpu-layers -1`): needs a CUDA `llama-cpp-python`. The **daemon venv**
  (`~/.local/share/red-pill/daemon/.venv`) is the CUDA build; measured ~1 s/probe for the 8B
  models on an RTX 5070 (8 GB).
- **All-CPU** (`--n-gpu-layers 0`): the **project venv** ships a CPU build; ~9 s/probe for a
  9B. Correct for hosts without a GPU or when VRAM is reserved for training.
- **Hybrid** (`--n-gpu-layers N`): N layers on GPU, the rest on CPU — how the sleep cycle
  actually runs when VRAM is partially occupied (the "Be Water" fallback, AD-020).

> Note: a reasoning-trace model may emit `<think>` blocks or a prose preamble that eats the
> token budget before the JSON closes. If `json_ok` is unexpectedly low, re-run with a larger
> `--max-tokens` before concluding a model "can't do JSON".

## Findings (bake-off 2026-07-13, GPU RTX 5070 8 GB, 512 max-tokens)

| Model | JSON | Spanish | No `<think>` | Emotion ok | Avg latency | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **hermes_8b** | 4/4 | 4/4 | 4/4 | 4/4 | 1.0 s | co-winner — clean format, complete summaries |
| **granite_8b** | 4/4 | 4/4¹ | 4/4 | 4/4 | 1.0 s | co-winner — clean format, best noise restraint, Apache-2.0 |
| piaget_8b | 4/4 | 4/4 | 0/4 | 4/4 | 0.9 s | alt — best abstraction, `<think>` tax |
| beck_8b | 4/4 | 4/4 | 0/4 | 4/4 | 1.0 s | copied input verbatim on emotional probe |
| qwen35_9b | 1/4 | 1/4 | 4/4 | 1/4 | 9.5 s | NOT distiller — prose "Thinking Process", blows budget |
| samantha | 0/4 | 0/4 | 4/4 | 0/4 | 2.6 s | retired legacy baseline |

¹ The cheap language heuristic false-flagged one Granite summary as English (no accents / too
few stopwords); it was in fact Spanish, so Granite is 4/4. On the noise probe Granite rated
intensity 0.3 vs Hermes' 0.6 — better restraint for the culling filter.

### Fidelity (both-sides) + prompt tuning — `scripts/distiller_fidelity.py`

Format is a tie between hermes_8b and granite_8b, so a second eval checked whether the summary
captures BOTH the user's point AND the assistant's response (deterministic per-side keyword
coverage over 3 two-voice interactions), comparing a BASE prompt vs a TUNED one that explicitly
demands both sides:

| Model | BASE both-sides | TUNED both-sides |
| :--- | :--- | :--- |
| hermes_8b | 2/3 | **3/3** |
| granite_8b | 2/3 | **3/3** |

**It is a prompt problem, not a model problem.** Under BASE each model drops one side on one
probe (Hermes on caching, Granite on philosophy); under TUNED both reach 3/3 with visibly better
summaries ("*El usuario… el asistente discrepa/advierte/decide…*"). The both-sides instruction is
now in the production `distill_engram` prompt (`metabolism/sleep.py`) — a model-agnostic quality
win. See [DISTILLER_FIDELITY.md](../../BENCHMARKS/DISTILLER_FIDELITY.md).

**Net:** hermes_8b and granite_8b are co-winners on both format and (tuned) fidelity.

**Decision (AD-022, operator-ratified):** **granite_8b is the primary distiller** (sole
`distillation` capability, `MINION_PROFILE=granite_8b`), **hermes_8b is the fallback** (keeps
`logic`/`emotional_intelligence`). Granite won the tiebreakers — Apache-2.0 license, small-expert
fit, efficiency — while Hermes stays as the arch-risk safety net (promote it if a future
llama.cpp cannot load Granite's hybrid architecture).

**Outcome:** the bake-off overturned the a-priori favorite. Qwen3.5-9B is a strong generalist
but ignores the "no reasoning" instruction and rarely closes valid JSON; **hermes_8b** is the
production distiller (sole `distillation` capability), with **piaget_8b** as the affective-depth
alternative. `samantha` is retired from the role. See `DISTILLER_BAKEOFF.md` for raw outputs.

---

## Memento agentic pass — distiller/curator selection (bake-off 2026-09-14)

A **second, distinct use** of distillation: the RFC-002 Memento file-based pass
(`memento/agentic/` — `distill_session` → `refine_session`), which summarises
sessions to disk and judges their long-term value. Unlike the sleep distiller
(short raw interactions, small context), this pass faces **long sessions** that
exceed the LLM window — so the model must also carry a **large context**.

### Requirements for this role
1. **Long context** — a session of 16K tokens must fit whole (no lossy truncation).
2. **Strict JSON** — distill `{title, summary, keywords}` and refine
   `{significance, emotion, intensity, theme, relics, cross_refs}`.
3. **Spanish fidelity + cross-refs** — summaries in Spanish; refine must relate a
   section to genuinely related sessions (`cross_refs`, critical for the
   reinforcement/weaving of Phase 4).
4. **Low VRAM** — leave room for the conversational model (Granite) on an 8 GB card.

### Method
- Load each candidate with `llama_cpp.Llama` (GPU, daemon venv), run the **same
  real target** (a Spanish implementation section) through the refine prompt at
  **n_ctx 8192 vs 32768**, and compare outputs (quality + determinism).
- Then run the **distill** prompt on a **real long split** (56.6K chars = 16049
  tokens) to confirm it fits whole at 32K.
- Guarded with `systemd-run --scope -p MemoryMax` (no OOM).

### Findings (GPU RTX 5070 8 GB, 2026-09-14)

**Refine quality** (same section, n_ctx 8192/32768 — output identical at both):

| Model | significance | relics | cross_refs | Typos | Gen |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **tiny-aya-water** | **0.7** | **4** ✓ | **2** ✓ | no | 1.5 s |
| tiny-aya-global | 0.7 | 6 (over limit) | 2 ✓ | no | 1.7 s |
| gemma-3-4b | 0.4 | 4 ✓ | 1 | no | 1.3 s |
| phi-4-mini | 0.2 | 3 ✓ | 1 | no | 1.4 s |
| llama-3.2-3b | 0.4 | 3 | **0** | yes | 1.1 s |

**Distill on a long session** (56.6K chars / 16049 tokens):

| Model | n_ctx | Fits whole? | VRAM | Gen |
| :--- | :--- | :--- | :--- | :--- |
| tiny-aya-water | 32768 | **yes** (16049 tok) | 6.3 GB | 15 s |
| tiny-aya-global | 32768 | yes | 6.3 GB | 15 s |

> Both Tiny Aya variants carry `context_length: 500000` in the GGUF (served at
> 32K here). At 8K the long session does **not** fit (16049 > 8192) — the
> motivation for the 32K profile.

### Decision (operator, 2026-09-14)
**`tiny_aya_water` is the Memento agentic-pass distiller+curator** at `n_ctx=32768`
(European-language variant → Spanish fidelity; disciplined format — respects the
4-relic cap; relates cross-refs). `tiny_aya_global` is the fallback.
**`gemma_3_4b` is the second (contrast) lens** for refine so the gate has
independent judges. `llama_3.2` is **discarded** for this role (0 cross_refs,
typos). Profiles registered in `model_profiles.yaml` (`tiny_aya_water`,
`tiny_aya_global`); catalog entry `local/tiny-aya-water`.

> This is **not** a replacement of `granite_8b` as the sleep distiller (AD-022) —
> it is a separate profile for the Memento pass, which needs long context that
> Granite's 10240 cannot provide.

> **Tiny Aya language flavours (Cohere Labs official).** The family ships four
> 3.35B variants (~2 GB each, huge context); pick by the operator's language
> family: **`tiny-aya-water`** = strongest for **Asia-Pacific & Europe** (our pick
> — Spanish); **`tiny-aya-earth`** = strongest for **Africa & West Asia**;
> **`tiny-aya-fire`** = strongest for **South Asian** languages;
> **`tiny-aya-global`** = best overall balance across all regions. Reasoning
> siblings (same backbone, 32K): `tiny-aya-l2-thinker` (thinks in the prompt
> language) and `tiny-aya-en-thinker` (English reasoning traces) — no official
> GGUF at the time of this bake-off, so not evaluated.

---

## Pase agéntico Memento (distill + refine file-based) — GRANITE (2026-09-15)

Distinto del distiller del sueño, el **pase Memento** (RFC-002 §4.5) produce los
`distill/*.md` y `refine/*.md` sobre el árbol. Tras el bake-off de prompts
(2026-09-15) la decisión es:

- **Modelo**: **Granite-4.1-8B** para TODAS las etapas (distill, refine WORK,
  refine SOCIAL). tiny-aya quedó descartado: sobre-genera ideas (4-7 por
  fragmento → ruido) y no separa work/social (clasifica contenido personal como
  work; la clasificación binaria lo llama `none`). Los parámetros de sampling
  (repeat_penalty, min_p, presence/frequency_penalty, seed) no corrigen el sesgo.

- **Fraccionado por contexto (n_ctx 10240)**: `MEMENTO_FRAGMENT_MAX_CHARS=8000`
  (antes 12000 para Aya 32K). El destilado por fases solapadas trocea work units
  > 8000 en fragmentos con solape de 2 mensajes; un turno individual gigante se
  sub-particiona por líneas. El presupuesto del refine (`model_prompt_budget`)
  es dinámico según el modelo servido. Verificado: 62K chars → 9 fragmentos que
  caben en granite y destilan en 1ª persona.

- **Prompts**: dos llamadas especializadas (`REFINE_WORK_USER` + 
  `REFINE_SOCIAL_USER`) — un solo prompt pedir ambos tipos confunde a los modelos
  locales (devuelven `[]` en contenido mixto). Voz en 1ª persona (`_VOICE_RULE`,
  MODE B: "Joan me cuenta... / le digo..."), alineada con el distiller V3.

- **Trazabilidad**: cada distill/refine guarda `engine` (modelo real) y
  `prompt_version` (hash de los prompts de la etapa) en el frontmatter; el
  registry `agentic` guarda `engine`, `distill_prompt_version`,
  `refine_prompt_version`.
