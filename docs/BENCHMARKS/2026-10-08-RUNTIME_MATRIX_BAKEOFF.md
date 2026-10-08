# Runtime matrix bake-off — 2026-10-08 12:37

> Matriz runtime × modelo (RFC-HARNESS-003): el mismo harness sirve cada
> modelo por su runtime anclado — Bonsai 2 27B PTQ1_0 exige el fork
> PrismML (`llama_cpp_prism`); Granite corre por el runtime stock.
>
> Medidas del PUESTO DE REFERENCIA (RTX 5070 Laptop 8 GB, sm_120a) —
> recalibrar por equipo (docs/CORE/CONVENTIONS.md §10.7).

```
model                               json                frases                  math
------------------------------------------------------------------------------------
bonsai_2_27b                     ✓ 10.8s               ✓ 26.9s               ✓ 11.3s
granite_4_2_8b                   ✓ 13.0s                ✗ 4.6s                ✓ 4.5s
```

## bonsai_2_27b
- math: {"valid": true} | 11.3s
  - out: 220
- json: {"valid": true, "keys": ["capital", "pais", "poblacion_millones"]} | 10.8s
  - out: {"pais":"España","capital":"Madrid","poblacion_millones":47.7}
- frases: {"valid": true, "frases": 3} | 26.9s
  - out: El mar Mediterráneo es un mar interior del hemisferio norte que conecta el océano Atlántico con el mar Rojo a través del canal de Suez. Sus costas abarcan 21 países y alberga una extraordinaria biodiversidad marina que ha sido objeto de múltiples programas de conservación. A lo largo de la historia,

## granite_4_2_8b
- math: {"valid": true} | 4.5s
  - out: We need to parse the question: "Un tren viaja a 80 km/h durante 2 horas y 45 minutos. ¿Cuántos km recorre? Responde solo con el número."  So train travels at speed 80 km/h for 2 hours and 45 minutes. Compute distance = speed * time.  Time = 2 hours + 45 minutes = 2 + 45/60 = 2 + 0.75 = 2.75 hours.  
- json: {"valid": true, "keys": ["capital", "pais", "poblacion_millones"]} | 13.0s
  - out: Okay, the user wants me to return only a valid JSON with the keys país, capital, and población_millones for Spain. No extra text.  First, I need to confirm the correct values. Spain's country name in Spanish is "España". Capital is Madrid. Population in millions—as of recent estimates, Spain's popul
- frases: {"valid": false, "frases": 20} | 4.6s
  - out: We need to respond with exactly 3 sentences in Spanish about the Mediterranean Sea. No lists, no titles. Just three sentences. Must be exactly three sentences. Should be simple. Ensure punctuation: sentences end with period. No extra sentences. No extra newline? Probably just plain text with three s
