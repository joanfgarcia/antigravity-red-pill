# Needle a ventana llena — `bonsai_25_27b` · KV `pq2_0m` (2 bits)

Mide lo que el modelo **lee**, no lo que el servidor acepta: dato único (código de
6 dígitos) sembrado al 62% de un texto de relleno reproducible, pregunta al final,
verificación por JSON. Una sesión por tamaño, semilla distinta por tamaño.

Herramienta: `scripts/needle_window.py`. Puesto: RTX 5070 Laptop 8 GB.

## Run 1 — ctx 112.048
| objetivo | prompt real | resultado | latencia |
| ---: | ---: | :--: | ---: |
| 25k | 21.580 | ✓ | 57,7 s |
| 50k | 43.085 | ✓ | 126,2 s |
| 75k | 64.567 | ✓ | 205,7 s |
| 100k | 86.072 | ✓ | 298,2 s |

## Run 2 — ctx 112.048, al borde
| objetivo | prompt real | resultado | latencia |
| ---: | ---: | :--: | ---: |
| 120k | **103.253** | ✓ | 378,5 s |

**5/5 recuperaciones correctas**, hasta 103.253 tokens de prompt con KV de 2 bits.
Prefill ≈ 270–290 tok/s: leer 100k cuesta ~6 min; la ventana es real, no gratis.
