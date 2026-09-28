# Bake-off F1 router System One — evidencia completa (AD-039, PARKED 2026-09-27)

Pregunta: ¿puede un modelo System One local (Laya) clasificar `dominio × voz`
por nota para elegir prompt (y modelo) antes de annotate? Respuesta: no
zero-shot; pendiente de re-evaluar con mejores checkpoints o fine-tune.

## Qué es cada pieza

- **Jev (TypeSafe, sep-2026)**: System One propietario, choice/score/noul
  calibrados, 70-500ms. Pesos cerrados + API hosted ($0.042/MTok) → descartado
  por egress (incompatible con soberanía).
- **Laya (Convai, Apache 2.0)**: equivalente auto-alojable, API compatible con
  Jev. Checkpoints: `english` (ModernBERT-large 421M, 512 ctx),
  `multilingual` (mmBERT-base 322M, 1024 ctx, 100+ idiomas),
  `typed-decisions` (ModernBERT-large afinado en workflows, 1024 ctx).
- **mmBERT** (JHU, sep-2025): encoder ModernBERT multilingüe (3T tokens,
  catalán en mid-training). Es YA el backbone del checkpoint multilingual —
  no hay primo mejor ahí fuera, falta afinar con nuestros datos.

## F1a — bake-off zero-shot (job `ea7387d9`, 9.9 min, CPU)

`scripts/laya_router_bakeoff.py` + `configs/jobs/laya_router_bakeoff.yaml`.
Muestra estratificada 40/40/40 (work/social/none) de 13.967 notas annotate.
Preguntas `dominio` (work/social/altre) + `actor` (joan/aleth/tercer/extern).

- Acuerdo dominio vs `dual_route`: **0,358** (gate F1→F2: ≥0,80 → NO PASA)
- Calibración **invertida**: conf ≥0,8 → acierto 0,29; conf <0,6 → 0,37
  (over-confidence típica de base sin tunear; la doc oficial lo documenta)
- Latencia p50/p95: 0,2s/0,28s por nota en CPU; escalado (conf<0,7): 29%
- Matriz: Laya vuelca 59/120 a `altre`; social→social solo 3/40

## F1b — adjudicación con juez LLM (job `6eac01d7`, 0.5 min, GPU)

`scripts/laya_adjudicate.py`: el juez (`_judge` de `memento_recalibrate`,
work/social binario) puntúa las mismas 120 en 5 lotes de 25.

- Baseline binaria vs juez: **0,85** (el 0,40 era del clasificador legacy;
  el dual-route actual ya está bien)
- Laya vs juez: **0,689**
- Duelo directo (16 desacuerdos binarios): baseline gana **13-3**

## F1c — ¿era el prompt? (interactivo, subset 30)

Esquema verificado contra el SDK (`instructions` + `criteria`, correcto).
4 variantes: catalán actual 0,367 / altre-restrictivo 0,400 / inglés 0,300 /
castellano 0,433. La aguja no se mueve; el volcado a `altre` persiste.
No es wording, es gap de distribución zero-shot.

## F1d — otros checkpoints (subset 30, V1)

english 0,400 (aviso: temperaturas inválidas → confianza sin calibrar) /
typed-decisions 0,433 / multilingual 0,400. Ninguno separa la distribución.

## Hallazgos de la doc oficial (laya-ai.com + nandhakishorm.github.io/laya)

- El wording y el ORDEN de opciones cambian respuestas; booleanos y
  negaciones fallan en ejemplos documentados → si se retoma, fijar orden.
- Base over-confident por defecto; calibrar temperaturas en held-out propio
  antes de cualquier gate por confianza (nuestro gate crudo era ingenuo).
- `typed-decisions` afinado: 0,766 donde los base ni pasan el baseline de
  mayoría → el fine-tune es LA vía, no otro checkpoint.
- Existe `laya-evals` (ECE, slices, gates CI) por si se retoma en serio.
- Fine-tune: notebook Kaggle 2xT4 + fuel propio (14.101 notas etiquetadas).

## Decisión PARKED y criterios de revisit (1 mes)

Aparcado porque: dual actual 0,85 + puntúa en batch (el ahorro de Laya es
marginal) + zero-shot 0,69 con calibración invertida. Retomar si: (a) sale
checkpoint multilingüe afinado en decisiones (no solo workflows en inglés),
(b) compensa el fine-tune (notebook + nuestras 14k), o (c) el dual baja de
0,80 en alguna recalibración. Re-ejecutar: venv
`~/.local/share/red-pill/laya-venv` + `scripts/laya_router_bakeoff.py`
(la muestra y los reportes crudos están en `state/laya_bakeoff/`, ignorado
por git; este doc es la evidencia duradera).
