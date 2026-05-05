# Antigravity Language Server Proxy (Ghost Cascade)

**Propósito:** Documentar el enlazamiento (hacking) entre el daemon de Red-Pill y el servidor local de Antigravity (Gemini), permitiendo la ejecución de inferencia "Headless" sin la intervención de la UI gráfica del IDE.

## 1. Conexión gRPC-Web Dinámica
El plugin del IDE de Antigravity expone un servidor gRPC-Web local. El puerto no es estático; se negocia en cada sesión y se escribe en un archivo local (ej. `.port` o se extrae mediante heurística en `ide_client.py`).
- **Endpoint:** `https://localhost:<PORT>/Antigravity.CascadeService/`
- **Seguridad:** Utiliza certificados TLS autofirmados (requiere deshabilitar la verificación SSL en el cliente Python `verify=False`) e inyección de token CSRF en las cabeceras (`X-IDE-CSRF-Token`).

## 2. El Payload de Inyección (SendUserCascadeMessage)
Para enviar un mensaje desde fuera del IDE sin que el parser protobuf de Antigravity descarte el payload, se requiere una serialización JSON sumamente específica.

### La Trampa del `oneof` en Protobuf
El esquema de `SendUserCascadeMessageRequest` define un array `items` en la raíz del objeto, donde cada ítem es de tipo `TextOrScopeItem`. En la definición de protobuf, el texto está encapsulado en un `oneof chunk`. 
Sin embargo, el mapeo estándar de Protobuf a JSON **elimina el nombre del envoltorio `oneof`** y eleva directamente el nombre del tipo seleccionado.

**Payload JSON CORRECTO:**
```json
{
  "cascadeId": "uuid-de-la-sesion",
  "items": [
    {
      "text": "Contenido del mensaje"
    }
  ],
  "cascadeConfig": {
    "plannerConfig": {
      "requestedModel": { "model": "MODEL_PLACEHOLDER_M37" },
      "conversational": { "plannerMode": "CONVERSATIONAL_PLANNER_MODE_DEFAULT" }
    }
  }
}
```
*Si se incluye `"userInput": { ... }` o `"chunk": { ... }`, el parser gRPC-Web descartará los campos desconocidos, inyectando un prompt literalmente vacío en el LLM (`USER: None`), causando alucinaciones o respuestas "en blanco".*

## 3. Extracción de Respuestas (Polling de Trayectoria)
El modelo de Antigravity es asíncrono. Enviar el mensaje no devuelve la respuesta inmediatamente.
- Red-Pill debe hacer polling mediante `GetCascadeTrajectory`.
- Se itera sobre el array `steps` de la trayectoria hasta encontrar el tipo `CORTEX_STEP_TYPE_PLANNER_RESPONSE` (Type 15) que indica que el LLM ha finalizado su planificación y respuesta de texto.
- Se lee el texto y se inserta en la tabla `outbox` de SQLite, completando el ciclo de ida y vuelta.
