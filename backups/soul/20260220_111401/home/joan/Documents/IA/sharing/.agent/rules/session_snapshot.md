# Session Snapshot: Red Pill v4.2.0 Remediation (Part 1)
**Date:** 2026-02-20

## 1. Diccionario de Alias Técnico
- **Búnker / Entorno**: `~/.agent/` y `IA_DIR`
- **Plan de Remediación**: `/home/joan/Documents/IA/sharing/docs/v4.2.0_remediation_plan.md`
- **Resumen Auditoría**: `/home/joan/tmp/audit_failures_summary.md`

## 2. Mapa de Arquitectura Técnica
- **Motor de Memoria**: `src/red_pill/memory.py` (Qdrant + FastEmbed HTTP client).
- **Scripts de Shell**: `scripts/*.sh` (Instaladores, Exportadores y Backups dependientes de bash).
- **Fix Crítico (IA_DIR)**: Todos los scripts bash ahora resuelven la ruta de anclaje mediante un nuevo archivo central `/home/joan/Documents/IA/sharing/scripts/env_loader.sh`.

## 3. Log de Decisiones Técnicas
| Prioridad | Decisión Técnica | Justificación | Estado |
| :--- | :--- | :--- | :--- |
| **CRÍTICA** | Inyectar `env_loader.sh` general | *GM-001/DS-002*: Múltiples lógicas para calcular `IA_DIR` causaron que el backup y la restauración apunten a lugares aleatorios. Centralizado unificador implementado. | ✅ Completado |
| **MAYOR** | Añadir flag `--dry-run` a `restore_all.sh` | *GM-002*: Riesgo inminente de sobreescritura letal en `$HOME`. Ahora por defecto simula el `rsync`, requiere `--commit`. | ✅ Completado |
| **MEDIA** | Condicional EUID para sudo en `install_neo.sh` | *LM-007*: Hardcodear `sudo` exponía al script a fallos según el gestor y riesgo de privilege escalation. Evaluado por usuario local y pasado como flag en variables. | ✅ Completado |

## 4. Última Frontera (Checkpoint)
- **Status Actual**: Planificación lista, Fase 1 terminada. Primera iteración de Fase 2 (Scripts bash / IA_DIR) codificada, testeada y commiteada (`feat/reactive-metabolism-v4.1.0 4e9e2f6`).
- **Siguiente Paso / Blocker**: Continuar con el siguiente punto crítico: (LM-001) Condición de carrera en `memory.py::_reinforce_points`. Se requiere editar la lógica en Python e introducir bloqueos, y (LM-002) inyección Pydantic.
