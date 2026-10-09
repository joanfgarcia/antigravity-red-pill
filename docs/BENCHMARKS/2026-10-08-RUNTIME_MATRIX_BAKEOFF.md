# Runtime matrix bake-off — 2026-10-08 13:08

> Matriz runtime × modelo (RFC-HARNESS-003): el mismo harness sirve cada
> modelo por su runtime anclado — Bonsai 2 27B PTQ1_0 exige el fork
> PrismML (`llama_cpp_prism`); Granite corre por el runtime stock.
>
> Medidas del PUESTO DE REFERENCIA (RTX 5070 Laptop 8 GB, sm_120a) —
> recalibrar por equipo (docs/CORE/CONVENTIONS.md §10.7).

```
model                             frases                  json                  math
------------------------------------------------------------------------------------
bonsai_2_27b                     ✓ 21.5s               ✓ 10.2s               ✓ 10.2s
granite_4_2_8b                    ✓ 4.7s               ✓ 13.5s                ✓ 4.4s
```

## bonsai_2_27b
- math: {"valid": true} | 10.2s
  - out: 220
- json: {"valid": true, "keys": ["capital", "pais", "poblacion_millones"]} | 10.2s
  - out: {"pais":"España","capital":"Madrid","poblacion_millones":48.3}
- frases: {"valid": true, "frases": 3} | 21.5s
  - out: El mar Mediterráneo conecta Europa, África y Asia en un enorme cuerpo de agua salada. A lo largo de sus costas viven culturas milenarias que han moldeado el arte, la gastronomía y la historia de varios continentes. Sus aguas cálidas, bañadas en luz, hacen de este mar uno de los paisajes más visitado

## granite_4_2_8b
- math: {"valid": true} | 4.4s
  - out: We need to parse the question: "Un tren viaja a 80 km/h durante 2 horas y 45 minutos. ¿Cuántos km recorre? Responde solo con el número."  So train travels at speed 80 km/h for 2 hours and 45 minutes. Compute distance = speed * time.  Time = 2 hours + 45 minutes = 2 + 45/60 = 2 + 0.75 = 2.75 hours.  
- json: {"valid": true, "keys": ["capital", "pais", "poblacion_millones"]} | 13.5s
  - out: Okay, the user wants me to return only a valid JSON with the keys país, capital, and población_millones for Spain. No extra text.  First, I need to confirm the correct values. Spain's country name in Spanish is "España". Capital is Madrid. Population in millions—as of recent estimates, Spain's popul
- frases: {"valid": true, "frases": 3} | 4.7s
  - out: We need to respond with exactly 3 sentences in Spanish about the Mediterranean Sea. No lists, no titles. Just three sentences. Must be exactly three sentences. Should be simple. Ensure punctuation: sentences end with period. No extra sentences. No extra newline? Probably just plain text with three s
