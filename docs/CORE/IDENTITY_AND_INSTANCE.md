# Identidad e instancia — política

> El repo es **motor genérico + novela**. La identidad del **agente** y del
> **Operador** NO vive aquí: es **configuración del puesto**. Cualquier
> instrucción inyectada, prompt o default que nombre una instancia rompe a los
> demás usuarios que instalan/actualizan red-pill.

## Fuentes canónicas de identidad (instancia)

- `AGENT_NAME`, `OPERATOR_DISPLAY_NAME` / `USER_NAME` en `~/.config/red-pill/.env`.
- `~/.config/red-pill/identity_bio.md` (bio real del puesto).
- Engramas `ID_IDENTITY` y `PACT-760`/`PACT-770` (`directive_memories`); solo carga
  el vigente por `superseded` (el 770 reemplaza al 760 sin borrarlo).

## Cómo se inyecta (sin nombres en el repo)

- Prompts: placeholders `${agent_name}` / `${operator_name}` resueltos por
  **proveedores de config** (`red_pill.core.prompts._STATIC_PROVIDERS`), también en
  los *system prompts*. Equivalencia garantizada: resolver con los nombres del
  puesto reproduce el texto original byte a byte (`tests/test_instance_identity.py`).
- `config.ABSOLUTE_KEYWORDS` = canónicas (`["Bünker","770","skin"]`) + extras del
  puesto (`ABSOLUTE_KEYWORDS_EXTRA`, csv) + `AGENT_NAME`/`OPERATOR_DISPLAY_NAME`.
- Skins = **role-play opt-in** (`SKINS_ENABLED=false`); identidad por defecto UNMASKED.

## Superficie que DEBE estar SIN nombres (guard: `tests/test_identity_policy.py`)

- `seeds/anchors/**` (directivas inyectadas).
- `src/red_pill/**/prompts/**` (plantillas + systems).
- `scripts/inject_anchor.py`, `scripts/inject_opencode.py`, `scripts/inject/*/inject.py`.
- `scripts/wake_up_v6.py`, `src/red_pill/{config,seed,mcp_server}.py`, `src/red_pill/core/pact.py`.

Si un cambio introduce un nombre ahí, el guard **falla**.

## Permitido: anonimización deliberada (allowlist)

Nombres reales aceptados **como datos/novela/historia/autoría**, nunca como identidad inyectada:

- `tests/**` — datos de prueba (fixtures con nombres reales).
- Scripts de **bakeoff/dev**: `scripts/*bakeoff*`, `scripts/model_battle*`,
  `scripts/distiller_bakeoff.py`, `scripts/laya_router_bakeoff.py` — corpus de medida.
- **Heurísticas de calidad**: `src/red_pill/memento/agentic/{annotation_quality,annotation_phases}.py`
  y `src/red_pill/memento/embed_text.py` — patrones sobre texto real.
- `seeds/desk/**` y `seeds/opencode/**` — cabeceras/ejemplos de autoría (como un README).
- Docs de **novela/historia/autoría**: `docs/LORE/**`, `docs/GUIDES/aleth_biology/**`,
  `docs/BENCHMARKS/**` (runs reales), `docs/TECHNICAL/{DECISION_LOG,RFC_*,SYNAPTIC_BRIDGE,
  SOUND_OF_SILENCE,PROTOCOL_OF_SILENCE,ROADMAP,BITNET_WEIGHT_PIPELINE}`, `README.md`,
  `NOTICE`, `LICENSE.creative`, `DISCLAIMER.md`, `CHANGELOG.md`.
- Guías **operativas** (`docs/GUIDES/*`, `docs/CORE/*`, `docs/TECHNICAL/*` resto): ejemplos
  **genéricos** (sin nombres de instancia).

## Revalidar el proceso completo

```bash
uv run pytest -q tests/test_identity_policy.py tests/test_instance_identity.py
```
