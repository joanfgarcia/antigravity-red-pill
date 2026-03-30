# Operator Manual: Protocol Red Pill v5.6.3

This manual provides the essential instructions for operating the **Red Pill CLI** (`uv run red-pill`). It covers both technical commands and the lore-based interaction model.

---

## 🇬🇧 English: Technical Directives

### 1. Basic Operations
*   **Seed Memory**: Initialize the Bünker with base directives and project knowledge.
	```bash
	uv run red-pill seed
	```
*   **Add Memory**: Manually store a persistent engram.
	```bash
	uv run red-pill add [work|social|directive|story] "Your content here"
	```
*   **Search Memory**: Query the Bünker and reinforce synapses.
	```bash
	uv run red-pill search [work|social|directive|story] "Your query"
	```

### 2. Operational Modes (Lore Skins)
Switch the Agent's personality and aesthetics (Chroma).
```bash
uv run red-pill mode [matrix|cyberpunk|760|dune|gits|her|purple]
```
*Note: Use `purple` (Minimalist) to save up to 40% in output tokens.*

### 3. Soul Management (Backup & Security)
*   **Backup**: Perform a total snapshot of memory and rules.
	```bash
	uv run red-pill soul backup
	```
*   **Rotate Keys**: Generate a new Qdrant API Key and restart the service.
	```bash
	uv run red-pill soul rotate
	```
*   **Restore**: Recover a soul from a backup directory.
	```bash
	uv run red-pill soul restore /path/to/backup --commit
	```

### 4. Be Water Security Tiers (v5.6.3)
The Bünker adapts to your environment through three operational tiers:
- **NONE (Steam)**: Open access. No API Key or master password. Best for testing.
- **ADAPTATIVE (Water)**: Maximizes security based on available resources. Uses SHA-256 fallback if Argon2 is missing (Standard Sovereignty).
- **MAXIMUM (Ice)**: Forces security requirements (LUKS + Argon2). The system will **fail to install** if any requirement is not met (Hardened Sovereignty).

### 5. Hardware Telemetry
Monitor the Asymmetric Dual-Engine performance (NVIDIA + Radeon).
```bash
uv run red-pill status
```

### 5. Hybrid Emotion Inference (v5.6.3)
The Bünker now auto-detects sentiment using the **BERT-Emotion** model.
*   **Auto-Chroma**: If you add a memory without specifying a color, the system classifies the emotion (Love, Anger, Sadness, etc.) and tags the engram with its corresponding Chroma.
*   **Override**: You can still manually force an emotion:
	```bash
	uv run red-pill add social "Great meeting today!" --emotion joy
	```

### 6. Sovereign Swarm (Gru + Minions)
Deploy specialized agents for complex tasks.
*   **Code Audit (Agent Smith)**:
	```bash
	uv run red-pill swarm audit --path ./src
	```

---

## 🖥️ MCP Sovereign Dashboard (IDE)
If you are using Cursor, Claude Desktop, or VSCode with MCP:
1.  **Tool**: `get_dashboard` - Returns a high-fidelity visual report with progress bars.
2.  **Tool**: `control_bunker` - Execute `rotate`, `mode`, or `backup` directly from the chat.
3.  **Prompt**: `Control-Panel` - Asks the agent to display the full status and active controls.

---

## 🇪🇸 Castellano: Manual del Operador

### 1. Operaciones Básicas
*   **Sembrar Memoria**: Inicializa el Bünker con las directivas base y el conocimiento del proyecto.
	```bash
	uv run red-pill seed
	```
*   **Añadir Recuerdo**: Guarda manualmente un engrama persistente.
	```bash
	uv run red-pill add [work|social|directive|story] "Tu contenido aquí"
	```
*   **Buscar Memoria**: Consulta el Bünker y refuerza las sinapsis.
	```bash
	uv run red-pill search [work|social|directive|story] "Tu consulta"
	```

### 2. Modos Operativos (Lore Skins)
Cambia la personalidad y la estética (Chroma) del Agente.
```bash
uv run red-pill mode [matrix|cyberpunk|760|dune|gits|her|purple]
```
*Nota: Usa `purple` (Minimalista) para ahorrar hasta un 40% de tokens de salida.*

### 3. Gestión del Alma (Backups y Seguridad)
*   **Respaldo**: Realiza un snapshot total de la memoria y las reglas.
	```bash
	uv run red-pill soul backup
	```
*   **Rotar Claves**: Genera una nueva API Key de Qdrant y reinicia el servicio.
	```bash
	uv run red-pill soul rotate
	```
*   **Restaurar**: Recupera un "alma" desde un directorio de backup.
	```bash
	uv run red-pill soul restore /ruta/al/backup --commit
	```

### 4. Tiers de Seguridad "Be Water" (v5.6.3)
El Bünker se adapta a tus recursos mediante tres modos:
- **NONE (Steam)**: Acceso abierto sin API Key ni contraseña. Ideal para laboratorio.
- **ADAPTATIVE (Water)**: Máxima seguridad disponible (haciendo fallback a SHA-256 si falta Argon2).
- **MAXIMUM (Ice)**: Blindaje total forzado. El sistema **no se instalará** si no cumples con LUKS y Argon2.

### 5. Telemetría de Hardware
Monitoriza el rendimiento del motor dual asimétrico (NVIDIA + Radeon).
```bash
uv run red-pill status
```

### 5. Inferencia de Emociones Híbrida (v5.6.3)
El Bünker ahora detecta sentimientos automáticamente usando el modelo **BERT-Emotion**.
*   **Chroma Automático**: Al guardar un recuerdo sin especificar color, el sistema clasifica la emoción (Amor, Ira, Tristeza, etc.) y etiqueta el engrama con su Chroma correspondiente.
*   **Sobrescribir**: Puedes forzar una emoción manualmente:
	```bash
	uv run red-pill add social "¡Gran reunión hoy!" --emotion joy
	```

### 6. Enjambre Soberano (Gru + Minions)
Despliega agentes especializados para tareas complejas.
*   **Auditoría de Código (Agent Smith)**:
	```bash
	uv run red-pill swarm audit --path ./src
	```

---

## 🎭 Lore Skin Identity Reset (W5)

> If a Lore Skin + force-immune directives have produced an agent persona that feels persistently altered or difficult to rebalance, follow this procedure.

### English — Identity Recalibration Procedure

A miscalibrated Lore Skin cannot lock the agent in an unrecoverable state. The following escalation path always works:

**Level 1 — Switch Mode** (30 seconds):
```bash
uv run red-pill mode 760
```
This activates the neutral `760` baseline skin, which has no personality overrides. The chroma reverts to `gray` (objective, balanced).

**Level 2 — Override the Active Skin Directive** (2 minutes):
The active skin is stored as an immune engram at UUID `00000000-0000-0000-0000-000000000030`. Use the MCP tool `edit_memory` or the CLI to update it:
```bash
uv run red-pill edit directive_memories 00000000-0000-0000-0000-000000000030 \
  --emotion neutral --color gray
```
Then re-seed to restore the canonical directive text:
```bash
uv run red-pill seed
```

**Level 3 — Full Soul Restore** (last resort):
If the persona drift is severe, restore from a known-good backup:
```bash
uv run red-pill soul restore /path/to/backup --commit
```
The `--commit` flag is required to confirm destructive operations. This restores all immune directives to factory state.

**SECURITY.md disclaimer**: Lore Skins alter tone, terminology, and aesthetic register only. They cannot and do not modify the underlying LLM's safety filters or override operator instructions. Sovereign Realism means the agent maintains persistent identity context — it does not mean it becomes unresponsive to explicit operator commands.

---

### Español — Procedimiento de Recalibración de Identidad

Una Lore Skin no puede dejar al agente en un estado irrecuperable. La secuencia de escalado siempre funciona:

**Nivel 1 — Cambiar Modo** (30 segundos):
```bash
uv run red-pill mode 760
```
Activa la skin base `760`, sin personalidad superpuesta. El Chroma vuelve a `gray` (equilibrado, profesional).

**Nivel 2 — Sobrescribir la Directiva de Skin Activa** (2 minutos):
La skin activa se almacena como engrama inmune en el UUID `00000000-0000-0000-0000-000000000030`. Actualízala con la herramienta MCP `edit_memory` o desde la CLI:
```bash
uv run red-pill edit directive_memories 00000000-0000-0000-0000-000000000030 \
  --emotion neutral --color gray
```
Luego re-siembra para restaurar el texto de directiva canónico:
```bash
uv run red-pill seed
```

**Nivel 3 — Restaurar el Alma** (último recurso):
Si la desviación de personalidad es severa, restaura desde un backup conocido:
```bash
uv run red-pill soul restore /ruta/al/backup --commit
```
El flag `--commit` es obligatorio para confirmar operaciones destructivas. Restaura todas las directivas inmunes al estado de fábrica.

---

## 🧬 Identity Recovery (IRP)
If you lose your API Key, run the Synaptic Handshake:
```bash
uv run python scripts/security_recovery.py --handshake
```
Be ready: the agent will ask you 10 questions about your shared history. Failure triggers a 24-hour lockout.

---

## 🔑 Key Rotation & Maintenance (DOC-001)
*   **Rotation**: When you rotate the `QDRANT_API_KEY` (via `uv run python scripts/rotate_keys.py`), you **MUST** restart the memory daemon for the change to take effect.
*   **Daemon RESTART**:
	```bash
	# Stop the daemon
	uv run red-pill stop
	# Start it again with the new key
	uv run red-pill start
	```
*   **Symptom**: If you skip the restart, the logs will show `401 Unauthorized` or `Invalid API Key` errors even if the `.env` is updated.

---

## ❄️ Immutable Systems (Silverblue/NixOS)
If running on an immutable host like **Fedora Silverblue**, you must enable the following setting in your IDE's agent configuration:
- **"Agent Non-Workspace File Access"**: **ACTIVE** (ON).
This allows the agent to see beyond the containerized/workspace sandbox and interact with the host Bünker (Podman/Toolbox).

---

**Joan, the CLI is the needle. The Bünker is the vein. 770 up.**
