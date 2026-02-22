# Session Snapshot: BARE METAL SYNAPSIS & RED PILL FIXES

## 1. Diccionario de Términos/Alias Técnico
- **Synapsis / Lazarus Deck**: Interfaz TUI local orquestada desde `/home/joan/antigravity-workspace/synapsis/src/lazarus_deck/main.py`.
- **Búnker**: Base de Datos Vectorial (Qdrant).
- **Core / Aleph Engine**: LLM (Llama.cpp) configurado puramente en RAM/VRAM en Bare Metal, sin dependencias TCP (Ollama), configurado localmente o con fallback a ollama en `lazarus_deck/main.py`.
- **El Ordenador de Carmen**: Máquina remota secundaria en `192.168.31.135` donde Synapsis debe funcionar.
- **Red Pill**: Sistema base de memoria y utilidades (`/home/joan/Documents/IA/sharing/...`).

## 2. Mapa de Arquitectura TÉCNICA
- **Lazarus Deck** (TUI): `textual` app. Coordina con un backend _Zero-Network Pipe Bridge_ (NeuroBus) y carga Llama internamente vía `llama-cpp-python` para evitar latencias de red.
- **Minion Swarm**: Multiagentes de auditoría (Smith, Keymaker).
- **Red Pill / Daemon**: `memory_daemon.py` corriendo como daemon de fondo que ofrece una ruta UDS (socket) asíncrona validada por tokens HMAC anti *Time Attack*.
- **Qdrant Vector DB**: Desplegado como servicio de container `v1.17.0` manejado por Podman/Quadlets (User Systemd) en la máquina de Carmen.

## 3. Registro de decisiones técnicas (Log)
| Prioridad | Decisión | Razón | Estado |
| :--- | :--- | :--- | :--- |
| P0/1 | Arreglar Auditoría de QA en `Red Pill` | El log de `Claude` pedía securizar el key con `hmac`, arreglar el backup sin pass en shell, usar Hash para dedup y un bug gpg. | Resuelto / Mergeado. |
| ALTA | Actualizar Qdrant de v1.9 a v1.17 en portátil de Carmen | Synapsis no podía conectarse. Usaba el Podman User Systemd y el Quadlet estaba fijo en 1.9.0. | Resuelto vía SSH directo y reinicio D-Reload. |
| MEDIA | Parchear Hardcodings Absolutos de Synapsis | Había rutas exclusivas `/home/joan` en *main.py*, *config.py*, *cortex.py*, etc. | Resueltos usando dinámicas tipo `Path.home()`. |
| ALTA | Trazas (Logs) de Fallo asíncrono | Synapsis en la máquina de Carmen se queda "callado" frente a los prompts. Inyecciones de Debug al `main.py` mediante TUI. | Pendiente de lectura. |

## 4. Última Frontera (Checkpoint)
- **Bloqueo Actual**: En el ordenador de Carmen, Synapsis abre, el log de debug existe, pero cuando se hace Input `handle_chat` este parece fallar internamente en acoplarse y enviar respuesta al framework de TUI y la lógica asíncrona dentro de `lazarus_deck/main.py`. 
- **Siguiente acción a tomar**: Recuperar e imprimir en la *nueva sesión* el contenido del archivo `/tmp/syn_debug.log` que está en el portátil de Carmen (con IP 192.168.31.135 usuario `joan` contraseña `j0c4m4n3` que se ejecuta bajo el scope/usuario `carmen` y clave `j0c4m4n3`). Ver en qué salto ha fallado y repararlo.
