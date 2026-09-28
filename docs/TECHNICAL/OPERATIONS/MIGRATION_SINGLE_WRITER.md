# Migración al single-writer de memoria (v8.0.0)

> **A quién afecta**: instalaciones que se **actualizan** desde una versión
> anterior al single-writer (v7.x) y tienen datos legacy. Las instalaciones
> **nuevas** nacen sin legacy y no necesitan nada.

## Qué cambia (breaking)

- Se **retira la ingesta legacy** `interaction_memories → work/social` del ciclo
  de sueño (drenaje + `staging/`), junto con los snatchers de IDE
  (`ls_snatcher`, plugin de Claude Code) y el staging de Telegram.
- La fuente de `work_memories`/`social_memories` pasa a ser **Memento**
  (chronicle → distill → refine/annotate → **ascensión**) + **síntesis de hubs**
  y **hilo de Ariadna** sobre los engramas curados.
- El buffer `interaction_memories` deja de consolidarse: es una **ventana corta**
  (pre-heating + tags), trimmada por el TTL del janitor.

## Migración automática (recomendada)

```bash
uv run python scripts/migrate_single_writer.py            # dry-run (no escribe)
uv run python scripts/migrate_single_writer.py --apply    # ejecuta
uv run python scripts/migrate_single_writer.py --apply --force   # re-ejecutar
```

Pasos que ejecuta:

1. **Cobertura**: cada sesión del registro Memento debe tener `raw/` o contenido
   **render** en Memento. Si falta alguna → **ABORTA** (no se migra con memoria
   sin archivar).
2. **Staging**: lo que quede en `staging/` se **archiva** en
   `staging/_migrated_<ts>/` (nunca se borra).
3. **Buffer**: `interaction_memories` más viejo que `INTERACTION_MAX_AGE_DAYS`
   (30d) se trima.
4. **Marca**: escribe `state/single_writer_migrated.json` (idempotencia).

Es **idempotente**: si la marca existe, no hace nada (salvo `--force`).

## Reconstrucción de `raw/` (upgrade 7.x → 8.x)

El migrador exige **cobertura** (cada sesión con `raw/` o render). Un 7.x no tiene
árbol Memento: se construye en la primera pasada desde los **stores nativos** de
los IDEs/CLI (la vía normal):

```bash
uv run python scripts/memento_migrate.py            # construye el delta (o todo si el árbol está vacío)
```

Si el store de un IDE ya no existe (rotado/purgado) y la sesión no tiene `raw/` ni
render, el migrador **abortará** nombrando las sesiones ausentes. Para recuperarlas
desde una colección Qdrant legacy que guarde turnos verbatim
(`session_id`/`sequence_index`/`role`/`raw_content`):

```bash
# El nombre de la colección lo das tú; nada está hardcodeado en el código.
uv run python scripts/memento_import_legacy.py --collection <coleccion>            # dry-run
uv run python scripts/memento_import_legacy.py --collection <coleccion> --apply    # reconstruye raw/ + render
uv run python scripts/migrate_single_writer.py --apply --drop-collection <coleccion>   # snapshot + drop
```

El importador infiere la fuente por el prefijo del `session_id` (`telegram:<uuid>` →
`telegram`) o usa `--source` para ids sin prefijo. Es idempotente: salta lo ya
cubierto (`--force` re-importa). `--drop-collection` toma **snapshot antes** de
borrar y aborta si el snapshot falla.


## Verificación post-migración

```bash
# Cobertura de hubs/hilo y salud del single-writer
uv run python -c "from red_pill.memory import MemoryManager; from red_pill.metabolism.sw_observability import compute_sw_health; import json; print(json.dumps(compute_sw_health(MemoryManager()), indent=2))"
```

- `work_memories`/`social_memories`: `hubs > 0` tras el primer ciclo de sueño.
- La síntesis de hubs es **idempotente** (`hub_input_hash`): las noches
  siguientes solo procesan sesiones nuevas o cambiadas.

## Flags

- **De migración** (desaparecen en la demolición, no se configuran):
  `SW_INGEST_RETIRED`.
- **De feature** (pasan a default ON o config; sin ritual):
  `SW_HUBS_ENABLED`, `SW_THREAD_ENABLED`, `SW_SITUATION_ENABLED`,
  `SW_EROSION_DEMOTE_ENABLED`, `MEMENTO_REALTIME_TAG_ENABLED` (RFC-004).

## Rollback

- Con el código nuevo no hay vuelta a la ingesta legacy (se elimina en la
  demolición). El archivo **Memento** (disco) y las copias `raw/` son el respaldo
  permanente.
- Si la migración aborta por cobertura, **no** se ha tocado nada: resuelve las
  sesiones sin archivar (renderiza su store con `memento_migrate.py`, o importa
  de una colección legacy con `memento_import_legacy.py`) y reintenta.

## Referencias

- Diseño y estado: `docs/TECHNICAL/BUNKER/RFC_002_PHASE4_DESIGN.md` §10.
- Rollout por piezas: `docs/TECHNICAL/OPERATIONS/SINGLE_WRITER_ROLLOUT.md`.
- RFC-004 (tags en vivo): `docs/TECHNICAL/BUNKER/RFC_004_REALTIME_TAG_SIDECAR.md`.
