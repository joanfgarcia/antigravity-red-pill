# Mapa de versiones de prompts (PROMPT-001, F1)

Registro del cambio de esquema de firmas introducido por **PROMPT-001 F1**
(2026-10-04). El proyecto (código) es la fuente de verdad; este documento es el
mapeo histórico que exige el RFC para interpretar artefactos sellados.

## Esquema

| | Antes (RFC-003) | Ahora (`p1:`) |
|---|---|---|
| Qué se hashea | Texto **crudo** de los ficheros de prompt (user) | **Prompt efectivo**: fragmentos + config resuelta (Bio, scopes, vista); runtime como sentinelas |
| Cobertura | Solo user prompts | Todos los prompts que emite la etapa, **system incluidos** (agregado por etapa) |
| Algoritmo | `sha256(...)[:10]` | `sha256` **completo**, prefijo `p1:` |
| Config | Solo annotate (Bio/scopes/vista) | Cada prompt declara sus estáticos; entran en la firma |
| Artefacto | — | `~/.local/share/red-pill/prompts/<componente>/<prompt>.<sig16>.txt` (0700/0600) |

## Mapeo

Firmas medidas con la config de test (`IDENTITY_BIO="TEST-BIO-FIXED"`, voz v2
OFF, vista `raw`). Las marcadas «no» no dependen de config y coinciden con
producción; `annotate` sí depende (Bio/scopes/vista/variante).

| Etapa | Hash antiguo (fecha/nota) | Firma nueva | ¿Depende de config? |
|---|---|---|---|
| distill | `66c679f1bb` (2026-09-23, RFC-003) · `64ab6661d1` (2026-10-03, idioma) | `p1:693b83e1…` | No |
| refine | `85209a6c9e` (2026-09-23) · `c79c7595a9` (2026-10-03, `memory`) · `69466365b9` (2026-10-03, idioma) | `p1:1cf95a51…` | No |
| annotate | `07a5c9b529` (v1 viva) · `3282c538f8` (test v1) · `4a31060ed9` (test v1+idioma) · `33d93aed78` (viva v1+idioma) | `p1:71854828…` (TEST-BIO-FIXED/v1/raw) | Sí (Bio, scopes, vista, variante) |
| validate | `217aafd8dd` (2026-09-23, v2 endurecido) | `p1:88a26e1b…` | No |

## Notas

- No hay migración automática de artefactos: el sellado nuevo marca stale lo
  antiguo y la regeneración usa la firma nueva (plan del RFC §3.6).
- La equivalencia byte-exacta del render (antes `str.format`, ahora
  `string.Template` + fragmentos) está cubierta por
  `tests/test_core_prompts.py` contra goldens pre-migración.
- La variante v2 de annotate (`MEMENTO_ANNOTATE_VOICE_V2=true`) tiene su propia
  firma agregada (work/social v2 + rewrite v2 + scorer v2 + sistemas).
