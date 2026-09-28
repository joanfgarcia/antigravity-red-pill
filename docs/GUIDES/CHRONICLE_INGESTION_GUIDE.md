# Chronicle Ingestion Guide

This guide documents the full pipeline to preserve and query historical Antigravity conversations in the Bünker memory substrate.

> **⚠️ ESTADO v8.0.0 (2026-09-28).** La ingesta legacy ha sido **retirada**:
> `archive_memories` está **purgada** (snapshot previo) y el destino de la
> memoria es el **árbol Memento en disco** + ascensión + hubs/hilo. El pipeline
> real lo ejecuta el **ciclo nocturno** (`redpill-nightly.timer`, 03:00 →
> `chronicle → sleep`). Los pasos manuales de más abajo son **HISTÓRICOS**
> (el descifrado/extracción sigue siendo útil como productor de
> `unencrypted_conversations/` para la fuente Memento de antigravity).

> **Memento Chronicle (RFC-002).** El chronicle **no escribe Qdrant**: renderiza
> cada sesión al árbol Memento en disco (`~/.local/share/red-pill/memento/`,
> canónico `memento/index.md` + `raw/`). El recall exacto lo sirve `search_memento`.
> La ingesta `archive_memories` fue **retirada** (v8.0.0) y la colección **purgada**.
> Ver [RFC_002_MEMENTO](../TECHNICAL/BUNKER/RFC_002_MEMENTO.md) y
> [ENV_REFERENCE](../ENV_REFERENCE.md).

## Prerequisites

-   Red Pill Protocol v8.0.0+ installed and running
-   Qdrant accessible at `$QDRANT_HOST:$QDRANT_PORT`
-   The Antigravity decryption key (see below)

---

## 🤖 Automated Mode (nightly, 03:00)

El **ciclo nocturno** (`redpill-nightly.timer` → `redpill-nightly.service`) es la
única entrada automática: encola `configs/jobs/nightly.yaml` (composition
`chronicle → sleep`). El chronicle renderiza el delta a Memento (disco) y el
sueño consolida, teje y asciende (hubs/hilo) — ya **sin** ingesta a
`archive_memories` (retirada).

**Verificar el timer (una vez por instalación/actualización):**
```bash
uv run python scripts/schedule_pulse.py --interval-hours 1
systemctl --user list-timers | grep nightly
# Esperado: redpill-nightly.timer  NEXT: tomorrow 03:00
```

**Catch-up manual:**
```bash
uv run python scripts/memento_migrate.py                 # render delta a Memento
uv run python scripts/memento_migrate.py --all           # reproceso completo
uv run red-pill job submit --recipe nightly --kick       # ciclo completo ahora
```

> **Persistent=true**: si el portátil estaba apagado a las 03:00, el timer se
> dispara al arrancar. Los timers individuales `redpill-chronicle.timer` y
> `redpill-sleep.timer` fueron **retirados** (decisión §5.3 opción A, AD-025).

---

## Step 1 — Obtain the Antigravity Key

The `.pb` conversation files are AES-encrypted. The key (`ANTIGRAVITY_KEY`) enables
the AES extraction path; without it the extractor falls back to the Language
Server. See [ANTIGRAVITY_KEY_RECOVERY](../TECHNICAL/SECURITY/ANTIGRAVITY_KEY_RECOVERY.md).

---

## Step 2 — Extract to `unencrypted_conversations/`

```bash
# Orchestrator: AES if ANTIGRAVITY_KEY is set, else Language Server.
uv run python scripts/chronicle_extractor.py
```

Output: `~/.local/share/red-pill/unencrypted_conversations/*.json` (one per
conversation). This is the **producer** of Memento's antigravity source.

> [!NOTE]
> `antigravity_decrypt.py` / `antigravity_ingest.py` (la vía que escribía a
> `archive_memories`) están **RETIRADOS** en v8.0.0.

---

## Step 3 — Render to Memento

```bash
uv run python scripts/memento_migrate.py            # delta
uv run python scripts/memento_migrate.py --all      # reproceso completo
uv run red-pill job submit --recipe nightly --kick  # ciclo completo ahora
```

El **ciclo nocturno** (`redpill-nightly.timer`, 03:00) hace esto automáticamente:
renderiza el delta al árbol Memento en disco y consolida (ascensión + hubs/hilo).
No hay ingesta a Qdrant en el chronicle.

---

## Step 4 — Ascensión a la memoria curada

`work_memories`/`social_memories` crecen **solo por ascensión de Memento**
(`distill→refine/annotate→ascend`) + síntesis de hubs. No se produce por drenaje
del buffer. Detalle: [OPERATIONS/SINGLE_WRITER_ROLLOUT.md](../TECHNICAL/OPERATIONS/SINGLE_WRITER_ROLLOUT.md).

---

## Step 5 — Consultar el archivo

```bash
# Recall exacto sobre el árbol Memento (MCP)
#   acción `search_memento`
# Consulta directa del árbol en disco:
ls ~/.local/share/red-pill/memento/
```

---

## Performance Notes

-   El archivo es **Memento en disco** (markdown + `raw/`); su destino es
    navegable y greppable. `work_memories`/`social_memories` son la capa curada.
-   El buffer `interaction_memories` es ventana corta (TTL `INTERACTION_MAX_AGE_DAYS`).

---

## Related Documents

-   [ANTIGRAVITY_KEY_RECOVERY.md](../TECHNICAL/SECURITY/ANTIGRAVITY_KEY_RECOVERY.md) — Key extraction protocol
-   [ARCHITECTURE.md](../TECHNICAL/ARCHITECTURE.md) — Memory collection design
-   [AGENT_UPDATE_GUIDE.md](AGENT_UPDATE_GUIDE.md) — Full update and maintenance flow
