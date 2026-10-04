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

Firmas finales medidas (2026-10-04, tras F1–F4) con `IDENTITY_BIO="TEST-BIO-FIXED"`,
voz v2 OFF, vista `raw` y `MEMENTO_PROMPT_LANGUAGE=auto`. Las firmas de distill,
refine y annotate **dependen del idioma** (`auto`/`es`/…): fijar otro idioma
produce firmas distintas a propósito. `validate` no depende de config.

| Etapa | Hashes antiguos (fecha/nota) | Firma nueva (auto) | ¿Depende de config? |
|---|---|---|---|
| distill | `66c679f1bb` (2026-09-23) · `64ab6661d1` (2026-10-03, idioma) | `p1:6d34dbc2…` | Sí (idioma) |
| refine | `85209a6c9e` (2026-09-23) · `c79c7595a9` (2026-10-03, `memory`) · `69466365b9` (2026-10-03, idioma) | `p1:0564c498…` | Sí (idioma) |
| annotate | `07a5c9b529` (v1 viva) · `3282c538f8` (test v1) · `4a31060ed9` (test v1+idioma) · `33d93aed78` (viva v1+idioma) | `p1:36199c3d…` (TEST-BIO-FIXED/v1/raw/auto) | Sí (Bio, scopes, vista, variante, idioma) |
| validate | `217aafd8dd` (2026-09-23, v2 endurecido) | `p1:215b61ac…` | No |

> Las firmas intermedias de F1/F2/F3 (`p1:693b83e1…`, `p1:cd872d97…`, etc.) ya no
> se emiten: la agregación de etapa usa prefijo de longitud desde el cierre del
> adversarial (2026-10-04). Esta tabla registra la versión vigente.

## Notas

- No hay migración automática de artefactos: el sellado nuevo marca stale lo
  antiguo y la regeneración usa la firma nueva (plan del RFC §3.6).
- La equivalencia byte-exacta del render (antes `str.format`, ahora
  `string.Template` + fragmentos) está cubierta por
  `tests/test_core_prompts.py` contra goldens pre-migración.
- La variante v2 de annotate (`MEMENTO_ANNOTATE_VOICE_V2=true`) tiene su propia
  firma agregada (work/social v2 + rewrite v2 + scorer v2 + sistemas).
