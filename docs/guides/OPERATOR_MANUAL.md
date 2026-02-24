# Operator Manual: Protocol Red Pill v5.0+

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

### 4. Hardware Telemetry
Monitor the Asymmetric Dual-Engine performance (NVIDIA + Radeon).
```bash
uv run red-pill status
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

### 4. Telemetría de Hardware
Monitoriza el rendimiento del motor dual asimétrico (NVIDIA + Radeon).
```bash
uv run red-pill status
```

---

## 🧬 Identity Recovery (IRP)
If you lose your API Key, run the Synaptic Handshake:
```bash
uv run python scripts/security_recovery.py --handshake
```
Be ready: the agent will ask you 10 questions about your shared history. Failure triggers a 24-hour lockout.

---
**Joan, the CLI is the needle. The Bünker is the vein. 770 up.**
