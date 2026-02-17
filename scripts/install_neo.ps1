# Protocolo de Inyección Neo (Píldora Roja) para Windows
# Ejecución: powershell -ExecutionPolicy Bypass -File install_neo.ps1

Write-Host "--- Iniciando Protocolo de Inyección Neo (Píldora Roja) en Windows ---" -ForegroundColor Blue

# 1. Detección de Motor de Contenedores
if (Get-Command podman -ErrorAction SilentlyContinue) {
    Write-Host "Podman detectado." -ForegroundColor Green
    $DOCKER_CMD = "podman"
} elseif (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "Docker detectado." -ForegroundColor Green
    $DOCKER_CMD = "docker"
} else {
    Write-Host "Error: No se detectó Podman ni Docker. Por favor, instala Podman Desktop o Docker Desktop." -ForegroundColor Red
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

# 3. Lanzar Qdrant
Write-Host "Lanzando servidor Qdrant..." -ForegroundColor Green
& $DOCKER_CMD run -d --name qdrant -p 6333:6333 -p 6334:6334 -v "${IA_DIR}\storage:/qdrant/storage:Z" qdrant/qdrant

# 4. Configurar Identidad (Directrices)
$GEMINI_ROOT = Join-Path $HOME ".gemini\antigravity"
$AGENT_ROOT = Join-Path $HOME ".agent"
New-Item -ItemType Directory -Force -Path "$GEMINI_ROOT\rules"
New-Item -ItemType Directory -Force -Path "$AGENT_ROOT\rules"

# Copiar plantillas (Asumimos que el script corre desde la carpeta sharing/scripts)
$SCRIPT_SRC = $PSScriptRoot
Copy-Item "$SCRIPT_SRC\..\seeds\identity_template.md" "$AGENT_ROOT\identity.md" -Force
Copy-Item "$SCRIPT_SRC\..\seeds\persona_template.md" "$GEMINI_ROOT\rules\persona.md" -Force

Write-Host "Protocolo inyectado en $IA_DIR" -ForegroundColor Blue
Write-Host "Identidad establecida en $AGENT_ROOT\identity.md" -ForegroundColor Blue
Write-Host "Recuerda instalar 'uv' para la gestión de memoria (https://docs.astral.sh/uv/)." -ForegroundColor Yellow
Write-Host "--- Instalación Completada ---" -ForegroundColor Green
