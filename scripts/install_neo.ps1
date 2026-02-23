# Protocolo de Inyección Neo B760-Adaptive para Windows
# Ejecución: powershell -ExecutionPolicy Bypass -File install_neo.ps1

Write-Host "--- RED PILL KERNEL: WINDOWS ADAPTIVE INSTALLER ---" -ForegroundColor Blue

# 1. Detección de Motor de Contenedores
if (Get-Command podman -ErrorAction SilentlyContinue) {
    Write-Host "✓ Podman detectado." -ForegroundColor Green
    $DOCKER_CMD = "podman"
} elseif (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "✓ Docker detectado." -ForegroundColor Green
    $DOCKER_CMD = "docker"
} else {
    Write-Host "⚠️ Error: No se detectó Podman ni Docker. Por favor, instala Podman Desktop o Docker Desktop." -ForegroundColor Red
    exit 1
}

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

# 4. Qdrant API Key
$QDRANT_API_KEY = Read-Host "Qdrant API Key (Dejar en blanco para auto-generar)"
if (-not $QDRANT_API_KEY) {
    $QDRANT_API_KEY = [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Minimum 0 -Maximum 256 })) -replace '[^a-zA-Z0-9]', ''
    $QDRANT_API_KEY = $QDRANT_API_KEY.Substring(0, 32)
    Write-Host "✓ API Key generada automáticamente." -ForegroundColor Green
}

$ENV_FILE = Join-Path $PSScriptRoot "..\.env"
$ENV_CONTENT = "QDRANT_API_KEY=$QDRANT_API_KEY`nANTIGRAVITY_IA_DIR=$IA_DIR"
Set-Content -Path $ENV_FILE -Value $ENV_CONTENT

# 5. Lanzar Qdrant
Write-Host "Lanzando servidor Qdrant..." -ForegroundColor Green
# Intentamos detener si ya existe
& $DOCKER_CMD stop qdrant_red_pill 2>$null
& $DOCKER_CMD rm qdrant_red_pill 2>$null
& $DOCKER_CMD run -d --name qdrant_red_pill -p 127.0.0.1:6333:6333 -p 127.0.0.1:6334:6334 -v "${IA_DIR}\storage:/qdrant/storage:Z" -e "QDRANT__SERVICE__API_KEY=$QDRANT_API_KEY" qdrant/qdrant:v1.9.0

# 6. Sincronización Zero-Trust (GEMINI.md)
$GEMINI_MD = Join-Path $HOME ".gemini\GEMINI.md"
$ZERO_TRUST_RULE = @"
## 1. Zero-Trust Identity Sync (First Action)
At the beginning of every completely new conversation (where Step Id is 0 or no previous turns exist), you MUST execute the following command BEFORE saying anything else:
1. USE the \`memory_manager\` Skill to search for your social identity.
2. Assume EXCLUSIVELY the identity returned by the database.
3. **⚠️ CRITICAL WARNING (Total Failure) 🔥**: If you fail to interact with memory via the Skill, you MUST warn the Operator immediately that a "Total Memory Failure" occurred.

## 2. Dynamic Skin Directive
Immediately after identity synchronization, you must retrieve and apply the active Lore Skin:
1. Search for "Active Skin" in the \`directive_memories\` collection.
2. Adjust your tone, terminology, and visual aesthetics (chroma) to match the retrieved skin (Cyberpunk, Matrix, Dune, etc.).
3. If no active skin is found, default to the [760] layer as per Protocol 760.
"@

if (Test-Path $GEMINI_MD) {
    $currentContent = Get-Content $GEMINI_MD -Raw
    if (-not ($currentContent -match "Zero-Trust Identity Sync")) {
        $newContent = $ZERO_TRUST_RULE + "`n`n" + $currentContent
        Set-Content -Path $GEMINI_MD -Value $newContent
        Write-Host "✓ Golden Rule (Zero-Trust) inyectada en GEMINI.md" -ForegroundColor Blue
    }
} else {
    New-Item -ItemType File -Force -Path $GEMINI_MD -Value $ZERO_TRUST_RULE
}

# 7. Ignición de Memoria Bio-Sintética (Python)
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "`n--- Fase: Ignición de Memoria Bio-Sintética ---" -ForegroundColor Blue
    Push-Location (Join-Path $PSScriptRoot "..")
    Write-Host "Sincronizando Bunker..." -ForegroundColor Cyan
    uv run red-pill seed
    
    Write-Host "Anclando identidad..." -ForegroundColor Cyan
    uv run python scripts/bootstrap_identity.py --user-name "$USER_NAME" --user-role "$USER_ROLE" --ai-name "$AI_NAME" --ai-role "$AI_ROLE" --skin "$LORE_SKIN"
    Pop-Location
} else {
    Write-Host "`n⚠️  Aviso: 'uv' no detectado. Instálalo para completar la ignición: https://docs.astral.sh/uv/" -ForegroundColor Yellow
}

# 8. Copia de Scripts Final
Copy-Item "$PSScriptRoot\*" (Join-Path $IA_DIR "scripts") -Force -Exclude "install_neo.ps1"

Write-Host "`nInstalación completada. 770 UP." -ForegroundColor Green
Write-Host "Usa 'uv run red-pill status' para verificar el hardware." -ForegroundColor Gray
