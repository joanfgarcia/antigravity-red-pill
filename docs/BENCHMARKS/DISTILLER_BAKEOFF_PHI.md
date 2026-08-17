# Distiller Bake-off Results

Heuristic aptitude scores per candidate. Operator confirms the winner.

## Aggregate (per model, across the battery)

| Model | JSON ok | Keys ok | Spanish | No <think> | No echo | Emotion ok | Avg latency |
|---|---|---|---|---|---|---|---|
| phi_mini | 4/4 | 4/4 | 3/4 | 4/4 | 4/4 | 4/4 | 1.29s |

## phi_mini
### technical — Technical distillation (work, strict JSON)
```json
{
  "summary": "Bug fix for tree_hash in pure-mls, 248 tests green. Confirmed, it was the missing leaf_index in RFC 9420 §7.8.",
  "emotion": "neutral",
  "intensity": 0.5,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "en", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 110, "latency_s": 1.86}`

### philosophical — Narrative/philosophical (social, Spanish fidelity)
```json
{
  "summary": "La identidad se forma por actos, no solo por recuerdos.",
  "emotion": "neutral",
  "intensity": 0.5,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 55, "latency_s": 1.11}`

### noise — Noise culling (should be neutral, low intensity)
```json
{
  "summary": "Reejecutar el linter con la opción --fix para FAILED tests",
  "emotion": "neutral",
  "intensity": 0.5,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 58, "latency_s": 1.07}`

### emotional — Emotional labeling (charged interaction)
```json
{
  "summary": "Joan ha ganado su entrenamiento después de tres noches sin dormir, sintiendo euforia.",
  "emotion": "joy",
  "intensity": 0.9,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 85, "latency_s": 1.11}`
