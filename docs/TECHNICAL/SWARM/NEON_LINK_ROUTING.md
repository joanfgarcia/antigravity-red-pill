# Motor de Políticas de Enrutamiento (Neon-Link Routing Engine)

Este documento detalla el diseño y flujo asíncrono del **Routing Policy Engine** implementado en `neon-link` y cómo interactúa con el `worker.py` del núcleo Soberano (Red-Pill).

La arquitectura está diseñada para proteger el contexto del LLM frente a picos de mensajes, separar intenciones inter-agencia de intenciones conversacionales y habilitar dinámicas emergentes (Agentic Emergence) en canales multi-usuario.

## Topologías de Canal

### 1. Telegram (Humanos a Máquina)
El canal de Telegram se clasifica evaluando si es un Grupo o un Mensaje Directo (DM).

- **Mensajes Directos (Private):**
  - **Modo por defecto:** `CONVERSATIONAL`
  - **Comandos Especiales:** Si empieza por `/bg`, el modo se fuerza a `BACKGROUND` y el prefijo se recorta.
- **Grupos y Supergrupos:**
  - **Modo por defecto:** `BACKGROUND` (Ingestión silenciosa).
  - **Excepción:** Si el Payload contiene explícitamente el username del bot (ej. `@redpill_bot`), se asume intención conversacional y pasa a `CONVERSATIONAL`.

### 2. Firebase (Máquina a Máquina / M2M)
El canal de Firebase recibe telemetría, engramas cifrados y mensajería del enjambre (Swarm). Todo pasa a través de una capa de Zero-Trust E2E (`pure-mls`).

- **Modo por defecto:** `BACKGROUND` (Protege al núcleo de interrupciones asíncronas).
- **Validación del Contrato:**
  - Tras desencriptar el payload, `firebase.py` extrae `group_size` y `priority`.
  - Si `priority == "critical"` **Y** `group_size <= 2`, el modo se eleva a `CONVERSATIONAL`.
  - Si el grupo es masivo (`group_size > 2`), se fuerza a `BACKGROUND` independientemente de la prioridad para prevenir tormentas de cascada.

---

## Flujo del Mensaje y Buffer de Compresión

### Diagrama General de Ingestión

```mermaid
sequenceDiagram
    participant User
    participant NeonLink (Telegram/Firebase)
    participant SQLite (events.db)
    participant Worker (Red-Pill)
    participant MinionInbox
    participant Antigravity (IDE)

    User->>NeonLink (Telegram/Firebase): Envía Mensaje
    Note over NeonLink (Telegram/Firebase): Routing Policy Engine evalúa<br/>chat_type, prefix, bot_mention y priority.
    NeonLink (Telegram/Firebase)->>SQLite (events.db): INSERT INTO inbox (mode='conversational'/'background')
    
    Worker (Red-Pill)->>SQLite (events.db): SELECT DISTINCT channel_user_id (PENDING)
    
    alt mode == 'background'
        Worker (Red-Pill)->>MinionInbox: drop_report(source, payload)
        Worker (Red-Pill)->>SQLite (events.db): UPDATE status = 'DELIVERED_BACKGROUND'
    else mode == 'conversational'
        Worker (Red-Pill)->>SQLite (events.db): SELECT all PENDING for channel_user_id
        Note over Worker (Red-Pill): [14:02] @alice: hi<br/>[14:03] @peter: yes
        Worker (Red-Pill)->>Antigravity (IDE): client.send_user_message(compacted_text)
        Worker (Red-Pill)->>SQLite (events.db): UPDATE status = 'WAITING_FOR_RESPONSE'
    end
```

### Diagrama de Comportamiento Emergente (Egress)

El sistema aprovecha la inteligencia contextual del LLM para resolver la interacción en grupos sin necesitar parseadores rígidos en Python.

```mermaid
sequenceDiagram
    participant Antigravity (IDE)
    participant Worker (Red-Pill)
    participant SQLite (events.db)
    participant NeonLink (Telegram)
    participant Alice & Peter

    Note over Antigravity (IDE): La IA lee el prompt compactado.<br/>Decide mencionar a los autores.
    Antigravity (IDE)-->>Worker (Red-Pill): Genera: "@alice entendido.\n@peter luego lo miro."
    Worker (Red-Pill)->>SQLite (events.db): INSERT INTO outbox (payload)
    Worker (Red-Pill)->>SQLite (events.db): UPDATE inbox SET status='PROCESSED' WHERE cascade_id=X
    NeonLink (Telegram)->>SQLite (events.db): SELECT FROM outbox (PENDING)
    NeonLink (Telegram)->>Alice & Peter: send_message(chat_id, "@alice ... @peter ...")
    Note over Alice & Peter: Las Apps de Telegram lanzan notificaciones<br/>Push nativas a los usuarios mencionados.
    NeonLink (Telegram)->>SQLite (events.db): UPDATE outbox SET status='SENT'
```
