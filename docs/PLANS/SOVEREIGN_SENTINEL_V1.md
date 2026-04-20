# Plan de Implementación: Autonomía Soberana (Sentinel & PSK)
**Estado**: Propuesta Técnica (Low-Profile / Local-Only)
**Versión**: v2026.04.09.1111

## 1. Fase Alpha: Sentinel Auditor (Infraestructura `sharing`)
El objetivo es transformar el `signal_memories` de un bus de eventos pasivo en un ciclo de retroalimentación activa.

### 1.1 `auditor.py` (The Log Weaver)
- **Ubicación**: `src/red_pill/metabolism/auditor.py`
- **Funcionalidad**:
    - Scaneo asíncrono del `MinionInbox` (SQLite).
    - Agrupación heurística de `PainSignals` por `FailureClass`.
    - Generación de "Briefing de Emergencia" en `work_memories` si la intensidad agregada supera `7.5`.
- **Checkpoint**: Commit local con el script base y el `systemd` user timer `redpill-auditor.timer`.

### 1.2 Auto-Healer Registry
- Vincular el auditor con `scripts/heal_cloud_sync.sh` y futuros auto-healers para dependencias (Mypy).

---

## 2. Fase Beta: Pure-MLS Phase 7 (Criptografía)
Cerrar los 41 xfails del IETF Interop para alcanzar la conformidad 1.0 total.

### 2.1 PSK (Pre-Shared Keys) Integration
- **Módulos**: `keyschedule.py` y `group.py`.
- **Tareas**:
    - Implementar el cálculo de `psk_secret` (HKDF-Extract de los PSKs inyectados).
    - Actualizar `join()` y `add_member()` para manejar `PSKLabel` y `PSKID` según RFC 9420 §9.
- **Validación**: Ejecución de `test_psk_vectors.py` (actualmente en `xfailed`).

### 2.2 Extension Frame Support
- Implementar el parsing de la extensión `ratchet_tree` (0x0004) como nodo de primer orden, eliminando el fallback legacy.

---

## 3. Fase Gamma: Resiliencia Cognitiva (Metabolismo)
Optimizar el ciclo de vida de la memoria para sesiones de alta intensidad de código.

### 3.1 Metabolic Dream Phase (v6.5.2)
- Modificación en `sleep.py`: Implementar una fase de **"Logical Distillation"**.
- En lugar de resúmenes genéricos, el sistema detectará patrones de cambio en archivos fuente (vía `work_memories`) y creará un mapa de dependencias temporal para la siguiente sesión.
- **Objetivo**: Evitar la amnesia de "por qué se tomó esta decisión de diseño" tras un reinicio de sistema.

---

## 4. Ejecución Planificada (Today — Low Profile)
1. [x] **Step 0**: `git commit` de estado actual (Hecho: `6cb73da`).
2. [ ] **Step 1**: Creación de `src/red_pill/metabolism/auditor.py` (Borrador).
3. [ ] **Step 2**: Primer intento de inyección de PSK en `pure_mls/keyschedule.py`.
4. [ ] **Step 3**: Actualización del CHANGELOG local para reflejar la visión v3.1.

> [!IMPORTANT]
> **Sovereignty Note**: No se realizará ningún `git push`. Todo el progreso se mantendrá en el Bünker local (`~/.gemini/antigravity`) y en el repositorio del usuario como commits sin publicar, para mantener el perfil bajo solicitado.
