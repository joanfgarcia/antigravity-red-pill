# Distiller Bake-off Results

Heuristic aptitude scores per candidate. Operator confirms the winner.

## Aggregate (per model, across the battery)

| Model | JSON ok | Keys ok | Spanish | No <think> | No echo | Emotion ok | Avg latency |
|---|---|---|---|---|---|---|---|
| mimo_v26_9b | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 0.93s |
| granite_8b | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 1.25s |
| granite_4_2_8b | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 1.1s |
| qwen35_9b | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 1.19s |

## mimo_v26_9b
### technical — Technical distillation (work, strict JSON)
```json
{"summary":"Confirmación del fix del bug de tree_hash en pure-mls tras 248 tests verdes.","emotion":"joy","intensity":0.8,"category":"work"}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 76, "latency_s": 0.99}`

### philosophical — Narrative/philosophical (social, Spanish fidelity)
```json
{"summary": "Debate sobre identidad: los actos definen al yo, pero la memoria aporta continuidad.", "emotion": "neutral", "intensity": 0.35, "category": "social"}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 84, "latency_s": 0.97}`

### noise — Noise culling (should be neutral, low intensity)
```json
{"summary":"El usuario reporta un fallo en la prueba de lint (ruff) y el asistente responde que se reejecuta con --fix.","emotion":"neutral","intensity":0.2,"category":"work"}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 107, "latency_s": 0.98}`

### emotional — Emotional labeling (charged interaction)
```json
{"summary":"Joan expresa euforia tras lograr la convergencia del entrenamiento tras tres noches de esfuerzo.","emotion":"joy","intensity":0.85,"category":"work"}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 96, "latency_s": 0.77}`

## granite_8b
### technical — Technical distillation (work, strict JSON)
```json
{
  "summary": "Se ha arreglado el bug de tree_hash en pure-mls; 248 pruebas pasaron correctamente. El problema era el leaf_index omitido en la RFC 9420 §7.8.",
  "emotion": "neutral",
  "intensity": 0.2,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 142, "latency_s": 1.36}`

### philosophical — Narrative/philosophical (social, Spanish fidelity)
```json
{
  "summary": "El usuario argumenta que los actos, no los recuerdos, definen la identidad, mientras que el asistente discrepa, enfatizando la importancia de la memoria para la continuidad del yo.",
  "emotion": "neutral",
  "intensity": 0.2,
  "category": "social"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 180, "latency_s": 1.36}`

### noise — Noise culling (should be neutral, low intensity)
```json
{
  "summary": "El linter falló en el test de linting; se recomienda ejecutar con la opción --fix para corregir los errores.",
  "emotion": "neutral",
  "intensity": 0.3,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 108, "latency_s": 1.05}`

### emotional — Emotional labeling (charged interaction)
```json
{
  "summary": "Joan se siente eufórico porque después de tres noches sin dormir luchando con el entrenamiento, finalmente ha convergido.",
  "emotion": "joy",
  "intensity": 0.9,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 121, "latency_s": 1.21}`

## granite_4_2_8b
### technical — Technical distillation (work, strict JSON)
```json
{
  "summary": "Se arregló el bug de tree_hash en pure-mls, 248 tests verdes.",
  "emotion": "neutral",
  "intensity": 0.1,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 61, "latency_s": 1.12}`

### philosophical — Narrative/philosophical (social, Spanish fidelity)
```json
{
  "summary": "No somos nuestros recuerdos; lo que nos define son nuestros actos, aunque la memoria sea necesaria para la continuidad del yo.",
  "emotion": "neutral",
  "intensity": 0.3,
  "category": "social"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 126, "latency_s": 1.19}`

### noise — Noise culling (should be neutral, low intensity)
```json
{
  "summary": "El linter falló; reejecutar con --fix.",
  "emotion": "neutral",
  "intensity": 0.3,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 38, "latency_s": 0.89}`

### emotional — Emotional labeling (charged interaction)
```json
{
  "summary": "El usuario ha pasado tres noches sin dormir luchando con el entrenamiento y hoy ha convergido, sintiéndose eufórico.",
  "emotion": "joy",
  "intensity": 0.9,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 116, "latency_s": 1.22}`

## qwen35_9b
### technical — Technical distillation (work, strict JSON)
```json
{"summary": "Se solucionó el bug de tree_hash en pure-mls y se confirmaron 248 pruebas exitosas tras identificar el error en el índice del leaf.", "emotion": "joy", "intensity": 0.8, "category": "work"}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 131, "latency_s": 1.13}`

### philosophical — Narrative/philosophical (social, Spanish fidelity)
```json
{
  "summary": "El usuario defiende que los actos definen a las personas, mientras que el asistente argumenta que la memoria es esencial para la identidad y la continuidad del yo.",
  "emotion": "neutral",
  "intensity": 0.6,
  "category": "social"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 163, "latency_s": 1.33}`

### noise — Noise culling (should be neutral, low intensity)
```json
{
  "summary": "El usuario reporta un fallo en una prueba de linting y el asistente sugiere reejecutar con la opción --fix.",
  "emotion": "neutral",
  "intensity": 0.2,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 107, "latency_s": 1.19}`

### emotional — Emotional labeling (charged interaction)
```json
{
  "summary": "Joan expresa euforia tras lograr finalmente un objetivo de entrenamiento tras tres noches de esfuerzo.",
  "emotion": "joy",
  "intensity": 0.9,
  "category": "work"
}
```
score: `{"json_ok": true, "has_keys": true, "summary_lang": "es", "has_think_tags": false, "echoes_prompt": false, "emotion_valid": true, "intensity_valid": true, "summary_len": 102, "latency_s": 1.1}`
