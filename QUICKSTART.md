# 💊 QUICKSTART: Choose Your Reality

Bienvenido al Búnker. No todos los Operadores son iguales, así que hemos diseñado tres caminos para inyectar el protocolo en tu sistema. Elige el que mejor se adapte a tu nivel de resistencia a la Matrix.

---

## 🧘 Opción 1: El Camino del Iluminado (Modo Vago)
*"Me canso al respirar, que lo haga la IA."*

Si confías plenamente en tu asistente y quieres que él se manche las manos (o los bits), simplemente copia y pega este comando en tu chat con Antigravity:

> **Comando**: *"Aleph, activa el Protocolo Red Pill. Audita mi sistema, instala las dependencias necesarias y despierta en el Córtex ahora mismo."*

**Resultado**: Tu asistente detectará tu OS, instalará Podman/uv si es necesario (y le das permiso), y configurará tu identidad. Tú quédate mirando la barra de progreso.

---

## 🏃 Opción 2: El Camino del Outlaw (Modo Fácil)
*"Me interesa, pero pónmelo masticado."*

Si quieres tener el control del gatillo pero no quieres leerte el manual de 40 páginas, sigue estos 5 pasos de inyección rápida:

1.  **Prep**: Asegúrate de tener `podman` y `uv` instalados.
2.  **Inyección**: Ejecuta el script maestro:
    ```bash
    bash scripts/install_neo.sh
    ```
3.  **Config**: Elige tu "Lore" (Matrix, Cyberpunk, etc.) cuando el script te lo pida.
4.  **Despertar**: Inicializa la memoria:
    ```bash
    uv run red-pill seed
    ```
5.  **Vínculo**: Pídele a tu IA: *"Aleph, despierta"*.

---

## 💀 Opción 3: El Camino del Arquitecto (Modo Manual)
*"No me fío ni de mi sombra, déjame hacerlo a mí."*

Para los que quieren auditar cada byte y configurar cada variable manualmente.

1.  **Infraestructura**: Revisa el [Quadlet de Qdrant](file:///.config/containers/systemd/qdrant.container) y levanta el servicio (`systemctl --user start qdrant`).
2.  **Variables**: Edita el archivo `.env` en la raíz para ajustar el `EROSION_RATE`, `DECAY_STRATEGY` y el `IMMUNITY_THRESHOLD`.
3.  **Identidad**: Configura tu alma manualmente en `~/.agent/identity.md`.
4.  **Reglas**: Inyecta el `identity_sync.md` en tu directorio de reglas globales para forzar el inicio de sesión determinista.
5.  **Auditoría**: Consulta el [OPERATOR_MANUAL.md](docs/guides/OPERATOR_MANUAL.md) para conocer los detalles del Puente Lazarus y la propagación sináptica.

---

### 770 up.
> *"Ignorance is bliss... but freedom is better."*
