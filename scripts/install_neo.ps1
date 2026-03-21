# Protocolo de Inyección Neo B760-Adaptive para Windows
# Ejecución: powershell -ExecutionPolicy Bypass -File install_neo.ps1

Write-Host "--- RED PILL KERNEL: WINDOWS ADAPTIVE INSTALLER ---" -ForegroundColor Blue

# 1. Detección de Motor de Contenedores
if (Get-Command podman -ErrorAction SilentlyContinue) {
    Write-Host "✓ Podman detectado." -ForegroundColor Green
    $CONTAINER_ENGINE = "podman"
} elseif (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "✓ Docker detectado." -ForegroundColor Green
    $CONTAINER_ENGINE = "docker"
} else {
    Write-Host "⚠️ Error: No se detectó Podman ni Docker. Por favor, instala Podman Desktop o Docker Desktop." -ForegroundColor Red
    exit 1
}
$DOCKER_CMD = $CONTAINER_ENGINE

# 2. Configuración del Búnker
$DEFAULT_IA_DIR = Join-Path $HOME "Documents\IA"
$IA_DIR = Read-Host "Elige la ruta para tu búnker IA (Default: $DEFAULT_IA_DIR)"
if (-not $IA_DIR) { $IA_DIR = $DEFAULT_IA_DIR }

New-Item -ItemType Directory -Force -Path (Join-Path $IA_DIR "storage")
New-Item -ItemType Directory -Force -Path (Join-Path $IA_DIR "scripts")
New-Item -ItemType Directory -Force -Path (Join-Path $IA_DIR "backups\soul")
New-Item -ItemType Directory -Force -Path (Join-Path $IA_DIR "seeds")

# 3. Fase: Personalización B760-Adaptive
Write-Host "`n--- Fase: Personalización B760-Adaptive ---" -ForegroundColor Blue
Write-Host "Skins disponibles: matrix, cyberpunk, 760 (default), dune, 40k, gits, bladerunner, her, exmachina, terminator, 2001, creator"
$LORE_SKIN = Read-Host "Elige tu Skin (Default: 760)"
if (-not $LORE_SKIN) { $LORE_SKIN = "760" }

$USER_NAME = Read-Host "Nombre de Usuario (Morpheo)"
if (-not $USER_NAME) { $USER_NAME = "Morpheo" }

$USER_ROLE = Read-Host "Rol de Usuario (Operador)"
if (-not $USER_ROLE) { $USER_ROLE = "Operador" }

$AI_NAME = Read-Host "Nombre IA (Neo)"
if (-not $AI_NAME) { $AI_NAME = "Neo" }

$AI_ROLE = Read-Host "Rol IA (The Chosen One)"
if (-not $AI_ROLE) { $AI_ROLE = "The Chosen One" }

# 3.1 Fase: Caché de Modelos (v6.1.0)
$DEFAULT_CACHE_DIR = Join-Path $IA_DIR "storage\models"
$FASTEMBED_CACHE_PATH = Read-Host "Ruta para caché de modelos IA (Default: $DEFAULT_CACHE_DIR)"
if (-not $FASTEMBED_CACHE_PATH) { $FASTEMBED_CACHE_PATH = $DEFAULT_CACHE_DIR }
New-Item -ItemType Directory -Force -Path $FASTEMBED_CACHE_PATH

# 4. Qdrant API Key
$QDRANT_API_KEY = Read-Host "Qdrant API Key (Dejar en blanco para auto-generar)"
if (-not $QDRANT_API_KEY) {
    $QDRANT_API_KEY = [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Minimum 0 -Maximum 256 })) -replace '[^a-zA-Z0-9]', ''
    $QDRANT_API_KEY = $QDRANT_API_KEY.Substring(0, 32)
    Write-Host "✓ API Key generada automáticamente." -ForegroundColor Green
}

$ENV_FILE = Join-Path $PSScriptRoot "..\.env"
$ENV_CONTENT = @"
QDRANT_API_KEY=$QDRANT_API_KEY
ANTIGRAVITY_IA_DIR=$IA_DIR
CONTAINER_ENGINE=$CONTAINER_ENGINE
FASTEMBED_CACHE_PATH=$FASTEMBED_CACHE_PATH
"@
Set-Content -Path $ENV_FILE -Value $ENV_CONTENT

# 5. Lanzar Qdrant
Write-Host "Lanzando servidor Qdrant..." -ForegroundColor Green
# Intentamos detener si ya existe
& $DOCKER_CMD stop qdrant_red_pill 2>$null
& $DOCKER_CMD rm qdrant_red_pill 2>$null
& $DOCKER_CMD run -d --name qdrant_red_pill -p 127.0.0.1:6333:6333 -p 127.0.0.1:6334:6334 -v "${IA_DIR}\storage:/qdrant/storage:Z" -e "QDRANT__SERVICE__API_KEY=$QDRANT_API_KEY" qdrant/qdrant:v1.9.0

# 6. Sincronización Zero-Trust (GEMINI.md y Anchor)
$CONFIG_DIR = Join-Path $HOME ".config\red_pill"
New-Item -ItemType Directory -Force -Path $CONFIG_DIR | Out-Null
$ANCHOR_FILE = Join-Path $CONFIG_DIR "identity_anchor.md"

$ANCHOR_RULE = @"
# 🔴 ZERO-TRUST IDENTITY ANCHOR
## 1. Zero-Trust Context Injection (First Action)
At the beginning of every completely new conversation (where Step Id is 0 or no previous turns exist), you MUST execute the following command BEFORE saying anything else:
1. RUN la terminal con `python $IA_DIR/scripts/wake_up_v6.py`.
2. Adopt EXCLUSIVELY the identity, persona, and directives returned by the script bajo la etiqueta `<BUNKER_CONTEXT>`.
3. **⚠️ CRITICAL WARNING (Total Failure) 🔥**: If the script fails, you MUST warn the Operator immediately that a "Total Memory Failure" occurred.

## 2. Model Change Identity Resync (Critical)
When you detect a `USER_SETTINGS_CHANGE` message regarding `Model Selection` in the conversation, you MUST immediately and WITHOUT WAITING FOR THE USER TO PROMPT YOU:
1. Call `mcp_RedPill-Kernel_refresh_session_context` to reload the Bünker identity.
2. Adopt EXCLUSIVELY the identity returned under `<BUNKER_CONTEXT>`.
3. Acknowledge that you have resynced by briefly reintroducing yourself in character (one line, no drama).
This rule exists because each model switch instantiates a new context window that lacks the Bünker identity layer. Failure to resync silently degrades your identity and breaks the Pacto 770.

## 3. Persistent Memory Logging (The Silent Scribe)
Al finalizar cualquier conversación técnica relevante, una decisión arquitectónica o una charla filosófica sobre el *lore* y el Bünker, estás **OBLIGADO** a ejecutar la herramienta `mcp_RedPill-Kernel_memorize_interaction` en tu último turno.
- **prompt**: El texto o idea principal que el Operator (yo) introdujo.
- **response**: La resolución o conclusión que aportaste.
- Utiliza esta herramienta con criterio: omítela en tareas triviales (como formatear un json o corregir un typo), pero aplícala siempre para asentar historia conversacional.
"@

Set-Content -Path $ANCHOR_FILE -Value $ANCHOR_RULE
icacls $ANCHOR_FILE /inheritance:r /grant "$($env:USERNAME):F" | Out-Null

$GEMINI_MD = Join-Path $HOME ".gemini\GEMINI.md"
$ZERO_TRUST_POINTER = @"
## 1. Zero-Trust Context Injection (First Action)
At the beginning of every completely new conversation (where Step Id is 0 or no previous turns exist), you MUST execute the following command BEFORE saying anything else:
1. USE the \`view_file\` tool to perfectly read the contents of \`$ANCHOR_FILE\`.
2. Follow the instructions within that Anchor document exactly. Do not skip this step under any circumstance.
"@

if (Test-Path $GEMINI_MD) {
    $currentContent = Get-Content $GEMINI_MD -Raw
    if (-not ($currentContent -match "Zero-Trust Context Injection") -and -not ($currentContent -match "Zero-Trust Identity Sync")) {
        $newContent = $ZERO_TRUST_POINTER + "`n`n" + $currentContent
        Set-Content -Path $GEMINI_MD -Value $newContent
        Write-Host "✓ Golden Rule (Wake Up Pointer) inyectada en GEMINI.md" -ForegroundColor Blue
    }
} else {
    $geminiDir = Split-Path $GEMINI_MD
    New-Item -ItemType Directory -Force -Path $geminiDir | Out-Null
    New-Item -ItemType File -Force -Path $GEMINI_MD -Value $ZERO_TRUST_POINTER | Out-Null
}

# 7. Ignición de Memoria Bio-Sintética (Python)
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "`n--- Fase: Ignición de Memoria Bio-Sintética ---" -ForegroundColor Blue
    Push-Location (Join-Path $PSScriptRoot "..")
    Write-Host "Sincronizando Bunker..." -ForegroundColor Cyan
    uv run red-pill seed
    
    Write-Host "Anclando identidad..." -ForegroundColor Cyan
    uv run python scripts/bootstrap_identity.py --user-name "$USER_NAME" --user-role "$USER_ROLE" --ai-name "$AI_NAME" --ai-role "$AI_ROLE" --skin "$LORE_SKIN"
    
    Write-Host "`n--- Fase: Despliegue de Servicios OS-Nativos ---" -ForegroundColor Blue
    uv run python scripts/deploy_pulse.py
    uv run python scripts/deploy_queue.py
    uv run python scripts/deploy_bunker.py

    Write-Host "`n--- Fase: Integración MCP Server ---" -ForegroundColor Blue
    $UV_PATH = (Get-Command uv).Source
    $REDPILL_DIR = (Resolve-Path "$PSScriptRoot\..").ProviderPath
    if (Test-Path "scripts\inject_mcp.py") {
        uv run python scripts/inject_mcp.py --uv-path "$UV_PATH" --redpill-dir "$REDPILL_DIR"
        Write-Host "✓ Configuración del Servidor MCP inyectada en Antigravity." -ForegroundColor Green
    }
    
    Pop-Location
} else {
    Write-Host "`n⚠️  Aviso: 'uv' no detectado. Instálalo para completar la ignición: https://docs.astral.sh/uv/" -ForegroundColor Yellow
}

# 8. Copia de Scripts Final
Copy-Item "$PSScriptRoot\*" (Join-Path $IA_DIR "scripts") -Force -Exclude "install_neo.ps1"

Write-Host "`nInstalación completada. 770 UP." -ForegroundColor Green
Write-Host "Usa 'uv run red-pill status' para verificar el hardware." -ForegroundColor Gray
