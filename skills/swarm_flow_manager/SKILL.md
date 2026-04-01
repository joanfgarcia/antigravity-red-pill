---
name: swarm_flow_manager
description: Administra el diseño, creación y persistencia de flujos autónomos de enjambre (Minions) en proyectos soberanos.
---

# Swarm Flow Manager Skill

Este skill permite al Agente (Antigravity) diseñar y persistir flujos de trabajo autónomos basándose en el registro central de Red-Pill pero aplicados a la soberanía de cada proyecto individual.

## Capacidades

1.  **Diseño de Flujos**: Capacidad para secuenciar Minions (`Ruff`, `Pytest`, `Smith`, `Samantha`) con políticas de control de errores (`on_fail: stop/warn`).
2.  **Persistencia Local**: Escritura de plantillas en la carpeta `.agent/flows.yaml` de cada proyecto para evitar polución del repositorio principal.
3.  **Validación de Orquestación**: Asegura que los minions referenciados existen en la `MinionFactory` de Red-Pill.

## Flujo de Trabajo

### 1. Crear o Actualizar un Flujo
Cuando el Operador o la tarea requiera un flujo nuevo (ej. `vulnerability-sweep`), el Agente debe:
- Identificar los minions necesarios.
- Definir la estrategia de encadenamiento.
- Escribir en `.agent/flows.yaml`.

```yaml
flows:
  [nombre-del-flujo]:
    name: "Nombre legible"
    description: "Propósito del flujo"
    steps:
      - minion: "id_del_minion"
        on_fail: "stop" # O "warn"
```

### 2. Ejecutar el Flujo
Una vez creado, el Agente puede invocar la herramienta del orquestador `run_autonomous_flow(flow_id)` para llevar a cabo la tarea sin intervención constante.

### 3. Capa Enterprise y Seguridad
El Agente debe ser consciente de las 3 capas de descubrimiento:
- **Global**: Red-Pill Core.
- **Community**: Firebase HUB (Workgroup).
- **Local**: Proyecto actual.

**Regla de Oro (Locking)**: Si un flujo tiene `locked: true` en la capa Global o Community, el Agente **no debe** intentar sobrescribirlo localmente. Debe informar al Operador sobre la política de cumplimiento activa.

### 4. Handovers de Enjambre
Para colaboración multi-agente, usa la propiedad `delegate_to: [Agente]`. El orquestador manejará el paso de mensajes asíncrono.

## Directrices de Diseño
- **Soberanía**: Nunca escribas flows globales en el núcleo si son específicos de un repo. Usa siempre `.agent/`.
- **Validación DRY_RUN**: Antes de persistir un flujo nuevo, realiza una validación mental de VRAM y dependencias de Minions.
- **Feedback**: Si un flujo falla repetidamente, el Agente debe proponer una reparación quirúrgica (`Healer`) como paso intermedio.
