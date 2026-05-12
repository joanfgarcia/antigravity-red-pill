# Neon-Link Edge Hub

**Propósito:** Interfaz de comunicaciones externas (Node.js/Python) que actúa como pasarela unidireccional (inyección) y bidireccional (polling) hacia el núcleo soberano de Red-Pill. Todo el tráfico del exterior se estandariza aquí.

## 1. Módulo Telegram (Telegraf / python-telegram-bot)
- **Función:** Recibir mensajes del usuario vía API de Telegram.
- **Riesgos:** La conexión HTTPS a Telegram y los servidores de Telegram no ofrecen cifrado extremo a extremo (E2EE) auditado para bots. Por tanto, el Edge Hub confía en TLS en tránsito.
- **Bot Token:** Configurado en entorno local (pendiente migración a `pure-mls` para eliminar el archivo `.env` del disco).

## 2. Módulo Firebase
- **Función:** Conexión con los flujos de base de datos en tiempo real de Google Firebase u otros webhooks externos.
- **Uso de Datos:** Puede traer notificaciones asíncronas, eventos de automatización, o datos que deben procesarse sin interrumpir al humano.

## 3. Inyección Estandarizada
Ninguno de los plugins ejecuta lógica pesada ni toma decisiones. Su única responsabilidad es parsear el mensaje crudo de su plataforma, encapsularlo en el contrato `Unified Event Bus Contract`, e inyectarlo de forma segura en la tabla `inbox` de la base de datos `events.db` (SQLite).

### Inyección desde Telegram (Ejemplo de `bot.py`)
```python
payload = json.dumps({
    "text": "mensaje enviado por el usuario",
    "mode": "conversational",  # Obligatorio: Indica que requiere respuesta inmediata
    "source": "telegram"
})

conn.execute(
    "INSERT INTO inbox (channel, channel_user_id, payload) VALUES (?, ?, ?)",
    ("telegram", chat_id, payload)
)
```

## 4. Polling de Respuestas
El hub ejecuta un bucle paralelo consultando la tabla `outbox` de `events.db`.
Si encuentra un mensaje con `status = 'PENDING'`, lee el `channel` y el `channel_user_id`, y despacha el mensaje a través del plugin correspondiente, marcando el registro como `DELIVERED`.
