# Protocolo Frankenstein: Orquestación de Vuelos (Manual de Trinchera)

**Estado**: `EXPERIMENTAL` | **Contexto**: Debugging E2E Flight Service (`bemotor` + `core` + `webcomponent`)

Este documento recopila la "Receta" exacta para levantar y depurar el entorno híbrido (Frankenstein) tal y como se definió en la sesión 760.

---

## 1. Preparación del Terreno (Infraestructura)

### A. La Bestia (Core / Tomcat)
Arrancar Tomcat con soporte para Debug remoto (JDWP) en el puerto **8001** (para evitar conflicto con el 8000 del Python).
```bash
cd /opt/servers/tomcat-9.0.113
export JPDA_ADDRESS=8001
./bin/catalina.sh jpda run
```
> **Nota**: Vigilar logs (`tail -f logs/catalina.out`) hasta ver "Server startup".

### B. Datos y Caché (Docker)
Levantar la base de datos y Redis.
```bash
# Desde la carpeta del proyecto
docker-compose up -d postgres redis
```

### C. El Parásito (Limpieza del Puerto 8000)
Liberar el puerto 8000 (usado habitualmente por Portainer o restos de Python).
```bash
docker stop portainer
# O buscar y matar:
kill -9 $(lsof -t -i:8000)
```

---

## 2. Fase Manual (Operador - Tú)

1.  **IDE Debug**: Conectar VSCode/IntelliJ al puerto **8001** (Remote JVM Debug).
2.  **Motor de Reservas**: Realizar una búsqueda y reserva de hotel hasta llegar al paso de pago/vuelo.
3.  **Extracción de Datos**: Capturar el `sessionId` y el `reference` de la URL o logs del Motor.
    *   *Ejemplo*: `sessionId: HPH#4#...`, `reference: TESTHTT...`
4.  **Entrega**: Facilitar estos datos al Agente (Neo).

---

## 3. Fase "Inteligente" (Agente - Neo)

1.  **Bemotor (Flight Microservice)**:
    *   Levantar el microservicio en el puerto **8090**.
    *   **Crucial**: Activar logs SLF4J en `WebhookController` para ver los callbacks.
    ```bash
    mvn spring-boot:run -Dspring-boot.run.profiles=local -Dserver.port=8090
    ```
2.  **Trigger (`flights/start`)**:
    *   Lanzar petición REST con los datos del Operador.
    ```bash
    curl -X POST http://localhost:8090/api/v1/flights/start ...
    ```
3.  **Token Handover**:
    *   El Agente captura la respuesta JSON y extrae el `opaque_token`.
    *   Lo presenta formateado en el chat para el Operador.
4.  **Vigilancia**:
    *   El Agente se queda monitoreando `bemotor_debug_slf4j.log` esperando el patrón `>>> WEBHOOK RECEIVED`.

---

## 4. Fase Final (Ejecución Híbrida)

1.  **Webcomponent (Python)**:
    *   El Operador (o el Agente) levanta el servidor web en el puerto **8000**.
    *   ```bash
        python3 -m http.server 8000
        ```
2.  **Navegación**:
    *   El Operador abre `http://localhost:8000` con el token facilitado.
    *   Realiza el flujo de reserva en la UI.
3.  **Confirmación**:
    *   El Agente confirma la recepción del Webhook en los logs del Bemotor.

---

**Nota Final**: Este "tinglado" es temporal hasta la integración nativa con el motor, pero mientras tanto... **funciona**.
