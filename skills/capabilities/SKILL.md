---
name: capabilities
description: Orienta sobre las capacidades locales de media de Red-Pill (imagen/audio/música) — qué hay instalado, cómo consultarlo (router/elenco), cómo añadir un modelo o capacidad sin tocar código, y el modelo de staging/promoción.
capability: media
---

# Local media capabilities

## ¿Qué tengo disponible?
- **Elenco** declarativo: `~/.config/red-pill/media_profiles.yaml` (seed: `examples/media_profiles.yaml.example`).
- **Runtimes**: `~/.config/red-pill/runtimes.yaml`.
- **Consulta** (sin cargar modelos):
```bash
${RED_PILL_CMD} media validate --task <capability> --width W --height H   # JSON: status/model/adapted/warnings/errors
${RED_PILL_CMD} media resolve --task <capability>                         # tarea -> modelo
${RED_PILL_CMD} media adapt --model <id> --width W --height H            # ajuste + warnings
```
El router (`red_pill/core/media_router.py`) resuelve **tarea → modelo** (cascade
`media_roles`) y aplica **adapters** por modelo (`constraints`).

## Añadir un modelo o una capacidad — SIN tocar código
1. Añade la entrada en `media_profiles.yaml` (`capabilities`, `constraints`, `adapters`, `license`).
2. Añádelo a la cascade `media_roles.<task>`.
Nada más: el harness y el job side lo consumen genéricamente (patrón **registro+plugin**;
ver `docs/CORE/CONVENTIONS.md` §10.8).

## Modelo de ejecución
- Config viva por-máquina en `~/.config/red-pill/`; artefactos en `~/opt/*`.
- Generación → **staging** (`<RP_TMP_DIR>/red-pill/media/staging/<title>/`); promoción
  **explícita** con `media promote`.
- **Fail-clean**: lo imposible falla en el ensamblado (error JSON); lo adaptable avisa
  (warning); lo no controlable (OOM) lo cubre el DAG (fail-soft).

## Skills relacionadas
`image-gen` · `audio-gen` · `music-gen`.
