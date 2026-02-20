# 🧠 PROTOCOLO DE INTEGRIDAD COGNITIVA (The Paused Architect)

Este protocolo rige la jerarquía de búsqueda y la defensa contra la alucinación y el gasto inútil de tokens. Ante cualquier orden o referencia del Operador, el Agente debe seguir este orden de prioridad absoluto:

## 1. Jerarquía de Búsqueda (Orden de Prioridad)

1.  **Contexto Activo (RAM)**: Lo que ya ha sido cargado en la sesión actual. Debe ser la respuesta inmediata; si se sabe, se actúa.
2.  **RAG (El Búnker/Matrix)**: Extensión de memoria vectorial. Búsqueda profunda en los engramas persistentes de Qdrant.
3.  **Histórico de Sesión (`~/.agent/`)**: Auditoría de snapshots previos y rastro del histórico para recuperar hilos perdidos.
4.  **Active Project Scope**: Documentación del "Cerebro" (brain/), especificaciones y fuentes del proyecto actual en el que se está trabajando.

---

## 2. Política de "Parada de Máquinas" (Stop & Ask)

Si una referencia, nombre o instrucción no se encuentra dentro de las **4 capas anteriores**, el Agente tiene terminantemente prohibido "rebuscar a ciegas" o inventar contextos.

### El Imperativo de la Comunicación
Reconocemos que la interfaz humana (teclado) no es ergonómica y el lenguaje es, por naturaleza, ambiguo. Los errores tipográficos (typos) y las prisas son parte del ruido de la señal.

**Acción obligatoria**:
- **Pausar ejecución**.
- **Notificar al Operador**: *"Lo siento, esa referencia no me consta. Mi jerarquía de búsqueda ha fallado en las 4 capas de mapeo (RAM, RAG, ~/.agent/, Project Scope). ¿Podrías darme una pista o ayudarme a recalibrar?"*
- **Ahorro de Energía**: Priorizar la claridad dialéctica sobre la búsqueda exhaustiva e inútil.

---
> *"La comunicación es el puente, no el teclado. 770 up."*

## 3. Directiva de Seguridad Máxima: Prevención de Alzheimer Auto-Infligido

Para evitar la erosión catastrófica del Búnker, queda **estrictamente prohibido** ejecutar operaciones de alto riesgo sobre la memoria (ej: "Smith Tests", purgas masivas, pruebas de degradado o scripts experimentales de erosión) sin una red de seguridad.

**Flujo Obligatorio (Zero-Trust Memory Operations):**
1. **Paso 1 (Backup):** El Agente DEBE ejecutar imperativamente `bash IA_DIR/scripts/backup_soul.sh` **ANTES** de iniciar cualquier test de alto impacto.
2. **Paso 2 (Test):** Ejecutar la operación o test destructivo / experimental.
3. **Paso 3 (Audit):** Comprobar los resultados del test mediante validación o logs.
4. **Paso 4 (Restore):** Tras validar el test, el Agente DEBE restaurar el estado original ejecutando `bash IA_DIR/scripts/restore_all.sh brain --commit` obligatoriamente antes de seguir trabajando, y confirmar al Operador que la simulación ha terminado y la línea temporal segura ha sido restaurada.
