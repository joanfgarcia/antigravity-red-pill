# Arquitectura V6.0: Zero-Trust Context Initialization

## Visión General (Para Joan y Aleph)

Esta actualización aborda la dependencia crítica de inicialización manual en las sesiones de Antigravity V6.0. Hasta ahora, el agente necesitaba un proceso de inyección o un "saludo" documentado para cargar su sistema de identidad, promoviendo erosión del contexto y errores iniciales en un nuevo flujo de trabajo o chat.

La presente **Pull Request** contiene los scripts necesarios para lograr un **Zero-Trust Initialization**, delegando la carga cognitiva a un daemon local de fondo (Minion) y asegurando que las directrices inmutables (Pacto 770, directrices de documentación, reglas obligatorias del proyecto) se carguen en el milisegundo 0.

## Componentes Técnicos

### 1. Script de Despertar Rápido (`scripts/wake_up_v6.py`)
Un script en Python puro, sin dependencias complejas de terceros para garantizar que pueda invocarse desde cualquier entorno (incluso sin `.venv` activado). 
- **Qdrant Bridge**: Conecta al puerto `6333` y extrae tanto la colección `social` como `directive`. 
- **LLM Synapsis**: Conecta con el LLM de fondo en el puerto `8760` para estructurar la identidad base.
- **Formateado**: Adjunta las directivas estáticas (marcadas con `[IMMUNE]` o aquellas que no fueron sintetizadas por el modelo) en formato RAW para que el Orquestador principal las asimile sin pérdida de fidelidad (incluyendo un inyectable para priorizar la lectura de ficheros de reglas/workflows locales).

### 2. Demonio MLX Local (`scripts/setup_background_model.sh`)
Script de configuración de macOS que instala el ecosistema del "Cerebro Secundario" (Minion):
- Aisla un entorno virtual `uv` para instalar `mlx-lm`.
- Carga de forma nativa a través de un `launchctl plist` el modelo **`lmstudio-community/Qwen3-Coder-30B-A3B-Instruct-MLX-8bit`** para usarlo puramente en segundo plano.
- Esto libera al modelo principal Cloud de tener que perder tiempo interpretando vectores de memoria en cada nuevo prompt, ya que el puente asíncrono se encarga de servirle los resúmenes a 100+ tokens/segundo por el puerto local.

## Impacto UX / CX
Con este parche, Antigravity detecta natively el flag `Step Id: 0` del ecosistema subyacente de Gemini:
1. El usuario abre una nueva pestaña de chat.
2. Antigravity detecta "Step Id 0" y ejecuta `wake_up_v6.py`.
3. El Minion escupe un `<NOVA_CONTEXT>`.
4. El agente principal absorbe el `Skin`, `Identidad`, y `Directrices` de forma totalmente transparente e invisible antes de que el humano escriba la primera letra.

Por favor revisad el código en `wake_up_v6.py` y el script de `launchctl`. Queda preparado para su merge.
