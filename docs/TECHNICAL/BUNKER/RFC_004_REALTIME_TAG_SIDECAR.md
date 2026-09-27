# RFC-004 — Etiquetado emocional en tiempo real (sidecar UDS, fail-visible)

| Field | Value |
|---|---|
| **RFC** | 004 |
| **Title** | Tag emoción/tema en captura vía sidecar UDS — señalizar, no garantizar |
| **Status** | ACCEPTED (diseño; implementación P1+P2 tras aprobación) |
| **Author** | Joan García (Operator) / Aleth (Agent) |
| **Created** | 2026-09-27 |
| **Related** | AD-040 (DECISION_LOG), AD-039 (router System One, parked), RFC-HARNESS-002 (daemon UDS) |

---

## 0. Resumen

Calibración emocional/temática **en tiempo real** del pre-heating mediante un
sidecar Laya (System One) que etiqueta cada turno en captura. Contrato central:
**el registro nunca espera; el fallo se señala, nunca se oculta ni se reintenta
en caliente**. Sin puerto TCP nuevo: todo por **UDS** (mismo patrón que el
daemon, `run_dual_bind.py`).

## 1. Contexto

- El pre-heating (Ferrari 11) calibra con la ventana caliente de
  `interaction_memories` (tier 2, 48h) + heurísticas. Tras la purga del buffer
  (2026-09-27) el tier 2 está vacío: degrada con gracia pero el hilo emocional
  en vivo pierde fuelle.
- AD-039 (router System One para elegir prompt) quedó PARKED: Laya zero-shot no
  separa la distribución de notas (0,36 dominio). **Este RFC no reactiva
  AD-039**: usa Laya donde sí encaja — presupuesto de ms, respuestas mínimas,
  fallo contenido (tono desviado, no recuerdo corrupto).
- El venv del daemon es GGUF (llama-cpp); Laya es torch/transformers → **venv
  propio** (`~/.local/share/red-pill/laya-venv`), nunca dentro del daemon.

## 2. Decisiones

### 2.1 Sidecar UDS (sin puerto TCP)
- `scripts/laya_tag_server.py`: servidor asyncio sobre
  `/run/user/1000/red-pill/laya_tag.sock` (permisos 0600, solo usuario).
- Carga `laya.load(..., subfolder='multilingual', device='cpu')` una vez
  (~18s en frío) y responde JSON por request (preguntas `emoción` + `tema`).
- Unit systemd `redpill-laya-tag.service` con `Restart=always` (mismo patrón
  que `redpill-llm.service`). Si cae, vuelve solo; si no vuelve, el tag no
  llega y el engrama lo señala. **Sin reintentos en caliente.**
- El cliente del worker: `socket.AF_UNIX` + timeout 2s + try/except total.

### 2.2 Tag en captura (`queue_worker.py`, punto único de drenaje)
- Tras `record_interaction_pair` (que **siempre** escribe), llamada
  fire-and-forget al sidecar. El registro nunca espera.
- El engrama lleva en `metadata`: `tag_status: ok|degraded|failed`, `reason`
  (timeout|sidecar-down|low-confidence), y si ok: `emotion`, `theme`,
  `confidence`.
- Flag `MEMENTO_REALTIME_TAG_ENABLED` (RULE 4, default OFF).

### 2.3 Consumo
- **Solera (M8):** promedia tags en vez de destilar texto. Sin tag → la entrada
  no entra en la media (ausencia de dato, no fallback).
- **Pre-heating (Ferrari 11):** tier 2 lee `tag_status: ok` recientes; si ve
  fallos, añade `CALIBRATION WEAK: últimos N turnos sin tag (motivo)`.
- Las heurísticas actuales quedan como **lectura por defecto cuando no hay
  tag** — no es fallback, es ausencia de dato.

### 2.4 Qdrant como ventana
- Últimos N por solera; trima lo existente (janitor TTL + sueño). Sin garantías
  nuevas ni operaciones exóticas: scroll por edad + delete, el patrón que ya
  usa `interaction_ttl`.

## 3. Plan de implementación

| Fase | Contenido | Gate |
|---|---|---|
| P1 | `laya_tag_server.py` + unit systemd + `MEMENTO_REALTIME_TAG_ENABLED` | Socket responde; carga <60s en frío |
| P2 | Tag en `queue_worker` (fire-and-forget, 2s) | Engramas con `tag_status` fluyendo |
| P3 | Solera consume tags | Situación se actualiza con tags |
| P4 | Pre-heating lee tags + línea WEAK | `CALIBRATION WEAK` visible en handshake |

## 4. Rollback

- Flag OFF → el worker no llama al sidecar; el resto es no-op.
- `systemctl --user stop redpill-laya-tag.service` → tags dejan de fluir; los
  engramas nuevos llevan `tag_status: failed` y el interceptor lo comunica.
- Nada de lo escrito es destructivo: los tags son metadata aditiva.

## 5. Por qué no alternativas

- **No puerto TCP:** superficie de ataque, firewall, auth. UDS 0600 = solo el
  usuario; mismo patrón que el daemon ya verificado.
- **No tag en el interceptor:** torch en el proceso caliente; los workers
  oneshot pagarían 18s de carga por tick.
- **No `laya-serve` (FastAPI):** el venv no trae fastapi/uvicorn y un servidor
  asyncio crudo UDS es ~60 líneas sin deps.
- **No reintentos:** el dato tardío no vale en tiempo real; la visibilidad
  (línea WEAK) es la garantía.
