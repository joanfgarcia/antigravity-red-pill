# Single-Writer Rollout Runbook (AD-034)

Guía operativa para **encender** el single-writer de memoria pieza a pieza (feature
flags por componente, CONVENTIONS RULE 4). Cada pieza es independiente, default
`OFF`, y **reversible**: se enciende, se verifica, y se pasa a la siguiente.

> Producción intacta mientras los flags estén `OFF`. Los scripts operativos
> (`memento_backfill_dates.py`, `memento_dedup_qdrant.py`) ya se aplicaron sobre el
> corpus (2026-09-21) con snapshots de Qdrant.

## 0. Precondiciones

- Rama `feat/memento-single-writer` desplegada en la máquina.
- Qdrant UP y **snapshot** reciente de `work_memories`/`social_memories`:
  ```bash
  .venv/bin/python -c "import red_pill.config as c; from qdrant_client import QdrantClient; \
    q=QdrantClient(url=c.QDRANT_URL, api_key=c.QDRANT_API_KEY); \
    print(q.create_snapshot('work_memories'), q.create_snapshot('social_memories'))"
  ```
- Suite verde: `.venv/bin/python -m pytest -q`.

## 1. Orden de encendido (dependencias)

| # | Flag | Efecto | Verificación |
|---|------|--------|--------------|
| 1 | `SW_AFFINITY_ENABLED` | Captura `session_id` en el buffer (afinidad **solo explícita**; la derivación por cwd se retiró — AD-034) | Filas nuevas de `memory_queue` con `session_id` |
| 2 | `MEMENTO_STATIC_ASCENSION_ENABLED` | Ascensión curada (work/social) | `ascend_by_threshold` asciende refines ≥ umbral de categoría |
| 3 | `SW_DEDUP_ENABLED` | Dedup-at-ascension (body-hash) | `duplicados_omitidos` > 0 solo para cuerpos idénticos |
| 4 | `SW_HUBS_ENABLED` | Hubs de sesión (idempotentes) | `node_type=synthesis_hub` creados; miembros `hubbed=true`; recall entra por el hub |
| 5 | `SW_THREAD_ENABLED` | Micro-hilo de Ariadna | `prev/next_member` en los miembros; `traverse_thread(level='member')` |
| 6 | `SW_INGEST_RETIRED` | Retira la ingesta `interaction→work/social` | No se escriben chunks/raw_parents desde el buffer; staging no crece |
| 7 | `SW_ABSENCE_GUARD_CONDITIONAL` + `SW_EROSION_DEMOTE_ENABLED` | Olvido: el pulse no refresca; demote a Memento | `last_recalled_at` envejece; demote a 5a/10a |
| 8 | `SW_SITUATION_ENABLED` | Semáforo de situación **GLOBAL** + pre-heating | `situation_memories` (afinidad `global`) con `situation_stable`/`situation_recent` |
| 9 | `SW_INTERACTIVE_PHASE_ENABLED` | Proceso de engramas interactivos | `red-pill add work ...` → `node_type=interactive_engram`; `interactive_refine.py` los marca |

**Regla**: no encender `SW_INGEST_RETIRED` (6) hasta que 2–5 estén sanos y
verificados (la fuente debe estar viva antes de cortar la vieja).

## 2. Verificación por paso

### Salud del single-writer (D26)
```bash
.venv/bin/python -c "from red_pill.memory import MemoryManager; \
  from red_pill.metabolism.sw_observability import compute_sw_health; \
  import json; print(json.dumps(compute_sw_health(MemoryManager()), indent=2))"
```
- `collections.*.hub_coverage_pct` > 0 con hubs encendidos.
- `solera_age_h` reciente (< 24h) con la solera activa.
- `affinity_coverage` — informativo: la afinidad es explícita/semántica (diferida), no se deriva del filesystem.

### Replay de recall (cobertura del agujero)
```bash
.venv/bin/python scripts/memento_replay_recall.py --limit 20
```
Debe devolver hits temáticamente relevantes (el replay de referencia dio 100% en 11 queries).

### Idempotencia de los scripts
```bash
.venv/bin/python scripts/memento_backfill_dates.py   # esperado: 0
.venv/bin/python scripts/memento_dedup_qdrant.py     # esperado: 0 réplicas
```

## 3. Rollback (por pieza)

Cada flag se apaga en `config`/`.env` y se reinicia el servicio correspondiente:
- `SW_HUBS_ENABLED=OFF` → el recall **vuelve a incluir** los miembros (la exclusión
  `hubbed` está gated); los hubs quedan inertes.
- `SW_INGEST_RETIRED=OFF` → vuelve la ingesta `interaction→work/social` (solo si NO
  se ha purgado el buffer; es la vía que se desea retirar definitivamente).
- `SW_EROSION_DEMOTE_ENABLED=OFF` → ningún demote.
- `SW_SITUATION_ENABLED=OFF` → el pre-heating no lee la solera.

> **Nota**: `SW_INGEST_RETIRED` es el único con "punto de no retorno" operativo:
> una vez retirado y con el buffer TTL'd, reactivarlo no recupera lo no destilado
> (Memento sigue siendo el archivo).

## 4. Señales de dolor

- `sw_solera_stale` — solera sin actualizar > 168h (¿drenaje/LLM parados?).
- `sw_hub_coverage` (status) — cobertura de hubs por colección.
- `interaction_unrendered_purged` — turnos sin renderizar purgados por el tope de edad (chronicle atrasado).
- `jobs_frustrated` / `task_failure` — ya existentes.

## 5. Recalibración de curaduría (recurrente)

Los umbrales de ascensión y el clasificador de categoría dependen del **modelo**
de las fases Memento (distill/refine): al cambiarlo, re-medir. Herramienta:
`scripts/memento_recalibrate.py`.

```bash
uv run python scripts/memento_recalibrate.py stats                        # distribución por categoría
uv run python scripts/memento_recalibrate.py bands --work 0.70 --social 0.65
uv run python scripts/memento_recalibrate.py audit-category -n 40 --engine <modelo>
uv run python scripts/memento_recalibrate.py audit-significance -n 30 --lo 0.55 --hi 0.65
uv run python scripts/memento_recalibrate.py report --work 0.70 --social 0.65
```

- `stats` / `bands` / `report` son deterministas (sin LLM): distribución de
  significance (ascendidos vs no), y escenarios de umbral (qué **entra**, qué
  **sale**, qué queda **al límite**) con muestras.
- `audit-category` mide el **acuerdo** del `category_score` contra el juicio del
  LLM (work/social/personal-history) → **base para decidir umbrales**.
- `audit-significance` mide el **% trivial** por banda: banda baja trivial →
  subir; banda alta con memoria valiosa → bajar.
- `--engine` fija `RP_LLM_MODEL` para comparar modelos (selección recurrente).

**Estado 2026-09-22** (cata preliminar): work 0.6 / social 0.5. La banda social
0.50-0.60 contiene **memoria personal de alto valor** (infancia, Carmen) mientras
el tramo work 0.60-0.65 es mayormente operativo → **antes de subir social hay que
calibrar el clasificador** (MEM-008, desk): hay contenido técnico cayendo en
`social` (umbral más bajo) y eso distorsiona la decisión. La estática sigue en
sombra; el backlog pendiente se recupera al encenderla con los umbrales vigentes
(upsert idempotente).
