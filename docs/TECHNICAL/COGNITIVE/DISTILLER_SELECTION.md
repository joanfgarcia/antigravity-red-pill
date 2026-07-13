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
| **hermes_8b** | 4/4 | 4/4 | 4/4 | 4/4 | 1.0 s | **PRIMARY** — cleanest format, no overhead |
| piaget_8b | 4/4 | 4/4 | 0/4 | 4/4 | 0.9 s | alt — best abstraction, `<think>` tax |
| beck_8b | 4/4 | 4/4 | 0/4 | 4/4 | 1.0 s | copied input verbatim on emotional probe |
| qwen35_9b | 1/4 | 1/4 | 4/4 | 1/4 | 9.5 s | NOT distiller — prose "Thinking Process", blows budget |
| samantha | 0/4 | 0/4 | 4/4 | 0/4 | 2.6 s | retired legacy baseline |

**Outcome:** the bake-off overturned the a-priori favorite. Qwen3.5-9B is a strong generalist
but ignores the "no reasoning" instruction and rarely closes valid JSON; **hermes_8b** is the
production distiller (sole `distillation` capability), with **piaget_8b** as the affective-depth
alternative. `samantha` is retired from the role. See `DISTILLER_BAKEOFF.md` for raw outputs.
