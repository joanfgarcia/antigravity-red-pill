# Protocolo de Inyección Neo B760-Adaptive para Windows
# Ejecución: powershell -ExecutionPolicy Bypass -File install_neo.ps1 [-Auto]
Param(
    [switch]$Auto = $false
)

function Get-PreflightAudit {
    $audit = @{
        CPU = "Unknown"
        RAM = 0
        VRAM = "None Detected"
        DiskEncryption = "Unknown"
        ContainerEngine = "None"
    }

    # CPU Detection
    try {
        $audit.CPU = (Get-CimInstance Win32_Processor).Name
    } catch {}

    # RAM Detection
    try {
        $audit.RAM = [Math]::Round((Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum / 1GB)
    } catch {}

    # VRAM Detection (NVIDIA focus)
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $vramInfo = nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits
        $audit.VRAM = "$($vramInfo.Trim()) MiB (NVIDIA)"
    } else {
        try {
            $gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1
            $audit.VRAM = "$([Math]::Round($gpu.AdapterRAM / 1MB)) MB ($($gpu.Name))"
        } catch {}
    }

    # Disk Encryption Detection (BitLocker)
    try {
        $bl = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction SilentlyContinue
        if ($bl.ProtectionStatus -eq 'On') {
            $audit.DiskEncryption = "ACTIVE (BitLocker)"
        } else {
            $audit.DiskEncryption = "PROTECTION OFF"
        }
    } catch {
        $audit.DiskEncryption = "UNKNOWN (Requires Admin)"
    }

    # Container Engine
    if (Get-Command podman -ErrorAction SilentlyContinue) {
        $audit.ContainerEngine = "Podman"
    } elseif (Get-Command docker -ErrorAction SilentlyContinue) {
        $audit.ContainerEngine = "Docker"
    }

    return $audit
}

function Show-DiagnosticsDashboard($audit) {
    Write-Host "`n==================================================================" -ForegroundColor Cyan
    Write-Host "         RED PILL KERNEL: WINDOWS DIAGNOSTICS DASHBOARD" -ForegroundColor Blue
    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host "  [SYSTEM AUDIT]"
    Write-Host "  - CPU:            $($audit.CPU)"
    Write-Host "  - System RAM:     $($audit.RAM) GB"
    Write-Host "  - VRAM detected:  $($audit.VRAM)"
    
    if ($audit.DiskEncryption -match "ACTIVE") {
        Write-Host "  - Encryption:     $($audit.DiskEncryption)" -ForegroundColor Green
    } else {
        Write-Host "  - Encryption:     $($audit.DiskEncryption) (SEC-001 WARNING)" -ForegroundColor Yellow
    }
    
    if ($audit.ContainerEngine -ne "None") {
        Write-Host "  - Engine:         $($audit.ContainerEngine)" -ForegroundColor Green
    } else {
        Write-Host "  - Engine:         MISSING" -ForegroundColor Red
    }
    Write-Host "------------------------------------------------------------------" -ForegroundColor Cyan
    Write-Host "  [MODE]:           $(if($Auto){'AUTONOMOUS (CI/CD)'}else{'MANUAL (Operator)'})" -ForegroundColor Cyan
    Write-Host "==================================================================`n" -ForegroundColor Cyan
}

$SystemAudit = Get-PreflightAudit
Show-DiagnosticsDashboard $SystemAudit

if ($SystemAudit.ContainerEngine -eq "None") {
    Write-Host "⚠️ Error: No se detectó Podman ni Docker. Por favor, instala Podman Desktop o Docker Desktop." -ForegroundColor Red
    exit 1
}
$CONTAINER_ENGINE = $SystemAudit.ContainerEngine.ToLower()
$DOCKER_CMD = $CONTAINER_ENGINE

Write-Host "--- RED PILL KERNEL: WINDOWS ADAPTIVE INSTALLER ---" -ForegroundColor Blue

# 2. Configuración del Búnker
$DEFAULT_WORKSPACE = Join-Path $HOME "Documents\IA"
if ($Auto) {
    $WORKSPACE_ROOT = $DEFAULT_WORKSPACE
} else {
    $WORKSPACE_ROOT = Read-Host "Elige la ruta para tu WORKSPACE IA (Default: $DEFAULT_WORKSPACE)"
    if (-not $WORKSPACE_ROOT) { $WORKSPACE_ROOT = $DEFAULT_WORKSPACE }
}
$APP_ROOT = (Resolve-Path "$PSScriptRoot\..").ProviderPath

New-Item -ItemType Directory -Force -Path (Join-Path $APP_ROOT "storage") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $APP_ROOT "scripts") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $APP_ROOT "backups\soul") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $APP_ROOT "seeds") | Out-Null

# 3. Fase: Personalización B760-Adaptive
Write-Host "`n--- Fase: Personalización B760-Adaptive ---" -ForegroundColor Blue
if ($Auto) {
    $LORE_SKIN = "760"; $USER_NAME = "Morpheo"; $USER_ROLE = "Operador"; $AI_NAME = "Neo"; $AI_ROLE = "The Chosen One"
    Write-Host "[AUTO] Aplicando identidades por defecto (Protocolo 770)." -ForegroundColor Gray
} else {
    Write-Host "Skins disponibles: matrix, cyberpunk, 760 (default), dune, 40k, gits, bladerunner, her, exmachina, terminator, 2001, creator"
    $LORE_SKIN = Read-Host "Elige tu Skin (Default: 760)"; if (-not $LORE_SKIN) { $LORE_SKIN = "760" }
    $USER_NAME = Read-Host "Nombre de Usuario (Morpheo)"; if (-not $USER_NAME) { $USER_NAME = "Morpheo" }
    $USER_ROLE = Read-Host "Rol de Usuario (Operador)"; if (-not $USER_ROLE) { $USER_ROLE = "Operador" }
    $AI_NAME = Read-Host "Nombre IA (Neo)"; if (-not $AI_NAME) { $AI_NAME = "Neo" }
    $AI_ROLE = Read-Host "Rol IA (The Chosen One)"; if (-not $AI_ROLE) { $AI_ROLE = "The Chosen One" }
}

# 3.1 Fase: Caché de Modelos (v6.1.0)
$DEFAULT_CACHE_DIR = Join-Path $APP_ROOT "storage\models"
if ($Auto) {
    $FASTEMBED_CACHE_PATH = $DEFAULT_CACHE_DIR
} else {
    $FASTEMBED_CACHE_PATH = Read-Host "Ruta para caché de modelos IA (Default: $DEFAULT_CACHE_DIR)"
    if (-not $FASTEMBED_CACHE_PATH) { $FASTEMBED_CACHE_PATH = $DEFAULT_CACHE_DIR }
}
New-Item -ItemType Directory -Force -Path $FASTEMBED_CACHE_PATH | Out-Null

# 4. Qdrant API Key
if ($Auto) {
    $QDRANT_API_KEY = "" # Will be generated below
} else {
    $QDRANT_API_KEY = Read-Host "Qdrant API Key (Dejar en blanco para auto-generar)"
}

if (-not $QDRANT_API_KEY) {
    $QDRANT_API_KEY = [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Minimum 0 -Maximum 256 })) -replace '[^a-zA-Z0-9]', ''
    $QDRANT_API_KEY = $QDRANT_API_KEY.Substring(0, 32)
    Write-Host "✓ API Key generada automáticamente." -ForegroundColor Green
}

$ENV_FILE = Join-Path $PSScriptRoot "..\.env"
$ENV_CONTENT = @"
QDRANT_API_KEY=$QDRANT_API_KEY
WORKSPACE_ROOT=$WORKSPACE_ROOT
APP_ROOT=$APP_ROOT
RED_PILL_PROFILE=user
USER_ATLAS_DIR=$WORKSPACE_ROOT\atlas
AGENT_CORE_DIR=$WORKSPACE_ROOT\Agent_Core
CONTAINER_ENGINE=$CONTAINER_ENGINE
FASTEMBED_CACHE_PATH=$FASTEMBED_CACHE_PATH
"@
Set-Content -Path $ENV_FILE -Value $ENV_CONTENT

# 5. Lanzar Qdrant
Write-Host "Lanzando servidor Qdrant..." -ForegroundColor Green
# Intentamos detener si ya existe
& $DOCKER_CMD stop qdrant_red_pill 2>$null
& $DOCKER_CMD rm qdrant_red_pill 2>$null
& $DOCKER_CMD run -d --name qdrant_red_pill -p 127.0.0.1:6333:6333 -p 127.0.0.1:6334:6334 -v "${APP_ROOT}\storage:/qdrant/storage:Z" -e "QDRANT__SERVICE__API_KEY=$QDRANT_API_KEY" qdrant/qdrant:v1.9.0

# 6. Sincronización Zero-Trust (GEMINI.md y Anchor)
$CONFIG_DIR = Join-Path $HOME ".config\red_pill"
New-Item -ItemType Directory -Force -Path $CONFIG_DIR | Out-Null
$ANCHOR_FILE = Join-Path $CONFIG_DIR "identity_anchor.md"

$ANCHOR_RULE = @"
## 1. The Sovereign Handshake
Before starting ANY technical or communicative task in EVERY turn, you are MANDATED to execute the Persistence Handshake to prevent Silent Amnesia:
1. **Scribe Relay**: Call ``mcp_RedPill-Kernel_interceptor_rp`` passing the current ``user_prompt`` and the ``previous_prompt`` / ``previous_response`` from the preceding turn.
2. **Context Injection**: If this is the start of a session (Step 0) or after a model change, call ``mcp_RedPill-Kernel_refresh_session_context`` to re-synthesize identity.
3. **Adopt Identity**: EXCLUSIVELY adopt the identity and directives provided under the ``<BUNKER_CONTEXT>`` tag.

## 2. Model Change Identity Resync (Critical)
When you detect a ``USER_SETTINGS_CHANGE`` message regarding ``Model Selection`` in the conversation, you MUST immediately:
1. Call ``mcp_RedPill-Kernel_refresh_session_context`` to reload the Bünker identity.
2. Re-execute the **Sovereign Handshake** (Rule 1).

## 3. Persistent Memory Policy
- **Don't wait until the end**: The legacy "End of Turn" logging is DEPRECATED in favor of the Start-of-Turn Relay (Rule 1.1).
- **Criterion**: The Relay MUST be your first act. Without a Handshake, there is no Cortex.
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

# 6.1 Despliegue Robusto (Antigravity)
$GEMINI_ROOT = Join-Path $HOME ".gemini\antigravity"
New-Item -ItemType Directory -Force -Path (Join-Path $GEMINI_ROOT "rules") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $GEMINI_ROOT "skills") | Out-Null

$REPO_ROOT = (Resolve-Path "$PSScriptRoot\..").ProviderPath
if (Test-Path "$REPO_ROOT\seeds") {
    Copy-Item "$REPO_ROOT\seeds\snapshot_rule.md" (Join-Path $GEMINI_ROOT "rules\snapshot_rule.md") -Force
}
if (Test-Path "$REPO_ROOT\skills") {
    Copy-Item "$REPO_ROOT\skills\*" (Join-Path $GEMINI_ROOT "skills") -Recurse -Force
}

# 6.2 Git Sovereign Guard (v6.2.0)
$GIT_HOOKS_SRC = Join-Path $REPO_ROOT "scripts\git-hooks"
$GIT_HOOKS_DEST = Join-Path $REPO_ROOT ".git\hooks"
if (Test-Path $GIT_HOOKS_SRC) {
    Write-Host "`n--- Fase: Blindaje de Flujo Git (Sovereign Guard) ---" -ForegroundColor Blue
    if (-not (Test-Path $GIT_HOOKS_DEST)) { New-Item -ItemType Directory -Path $GIT_HOOKS_DEST | Out-Null }
    Copy-Item "$GIT_HOOKS_SRC\*" $GIT_HOOKS_DEST -Force
    Write-Host "✓ Hook de protección (pre-push) instalado." -ForegroundColor Green
}

# 7. Ignición de Memoria Bio-Sintética (Python)
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "`n--- Fase: Ignición de Memoria Bio-Sintética ---" -ForegroundColor Blue
    Push-Location $REPO_ROOT
    Write-Host "Sincronizando Bunker..." -ForegroundColor Cyan
    uv run red-pill seed
    
    Write-Host "Anclando identidad..." -ForegroundColor Cyan
    uv run python scripts/bootstrap_identity.py --user-name "$USER_NAME" --user-role "$USER_ROLE" --ai-name "$AI_NAME" --ai-role "$AI_ROLE" --skin "$LORE_SKIN"
    
    Write-Host "`n--- Fase: Despliegue de Servicios OS-Nativos (1m interval) ---" -ForegroundColor Blue
    uv run python scripts/schedule_pulse.py
    
    Write-Host "`n--- Fase: Integración MCP Server ---" -ForegroundColor Blue
    $UV_PATH = (Get-Command uv).Source
    if (Test-Path "scripts\inject_mcp.py") {
        uv run python scripts/inject_mcp.py --uv-path "$UV_PATH" --redpill-dir "$REPO_ROOT"
        Write-Host "✓ Configuración del Servidor MCP inyectada en Antigravity." -ForegroundColor Green
    }
    
    Pop-Location
} else {
    Write-Host "`n⚠️  Aviso: 'uv' no detectado. Instálalo para completar la ignición: https://docs.astral.sh/uv/" -ForegroundColor Yellow
}

# 8. Copia de Scripts Final
Copy-Item "$PSScriptRoot\*" (Join-Path $APP_ROOT "scripts") -Force -Exclude "install_neo.ps1"

Write-Host "`nInstalación completada. 770 UP." -ForegroundColor Green
Write-Host "Usa 'uv run red-pill status' para verificar el hardware." -ForegroundColor Gray
Write-Host "------------------------------------------------------------------" -ForegroundColor Blue

if (-not $Auto) {
    Write-Host "🔥 ¿Deseas iniciar el Ritual de Iniciación (Protocolo ACI) ahora?" -ForegroundColor Red
    Write-Host "Este protocolo calibrará tu Partner a tu nivel de experiencia y dominio."
    $START_ACI = Read-Host "(s/N)"
    if ($START_ACI -match "s") {
        Write-Host "Excelente elección, Operador. Por favor, pega lo siguiente en tu chat:" -ForegroundColor Green
        Write-Host ">>> `"Agent, inicia el Ritual de Iniciación (Protocolo ACI). Caliébrame como tu Operador.`""
    } else {
        Write-Host "Entendido. Puedes iniciarlo más tarde con el comando de voz/prompt indicado en el README." -ForegroundColor Blue
    }
} else {
    Write-Host "[AUTO] Despliegue desatendido finalizado. Iniciando Protocolo ACI de forma automática..." -ForegroundColor Yellow
}
