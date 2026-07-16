---
name: telegram-gateway
description: Permite al agente enviar mensajes de notificación directa al operador a través de Telegram usando la configuración local de Neon-Link.
---

# Telegram Gateway (Neon-Link Communication)

Este Skill enseña al agente cómo enviar notificaciones y alertas al operador de forma proactiva a través del canal de Telegram, utilizando la infraestructura local de **Neon-Link**.

## 🔑 Credenciales y Configuración
El agente debe resolver las credenciales leyendo la configuración local del demonio **Neon-Link**:
- Ubicación típica de configuración: `neon-link/.env` (en el directorio de proyectos IA, ej: `~/Documents/IA/neon-link/.env`)
- Claves a buscar:
  - `TELEGRAM_BOT_TOKEN`: Token único del bot de Telegram.
  - `TELEGRAM_WHITELIST_ID`: ID o lista de IDs de Telegram autorizados para recibir notificaciones (usar el primer ID de la lista como chat_id principal).
  - `NEON_LINK_AGENT_ID`: Identificador del agente (nombre de la sesión o del avatar).

## 🚀 Método de Envío (HTTP POST)
El agente enviará los pings de estado haciendo peticiones POST directas a la API de Telegram.

### Curl (Terminal)
```bash
curl -s -X POST https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendMessage \
  -d chat_id=<TELEGRAM_WHITELIST_ID_FIRST> \
  -d text="[<AGENT_NAME>] <Tu mensaje aquí>"
```

### Python
El agente debe leer dinámicamente las credenciales en lugar de hardcodearlas:

```python
import os
import requests
from pathlib import Path

def get_neon_link_config():
	# Buscar el archivo .env en la ruta esperada
	possible_paths = [
		Path.home() / "Documents/IA/neon-link/.env",
		Path.home() / ".config/neon-link/.env",
		Path("./neon-link/.env")
	]
	
	config = {}
	for path in possible_paths:
		if path.exists():
			with open(path, encoding="utf-8") as f:
				for line in f:
					if "=" in line and not line.strip().startswith("#"):
						key, val = line.strip().split("=", 1)
						config[key.strip()] = val.strip().strip('"').strip("'")
			break
	return config

def send_telegram_ping(text: str, agent_name: str = "Agent"):
	config = get_neon_link_config()
	token = config.get("TELEGRAM_BOT_TOKEN")
	chat_id = config.get("TELEGRAM_WHITELIST_ID", "").split(",")[0].strip()
	
	if not token or not chat_id:
		raise ValueError("No se pudieron cargar las credenciales de Neon-Link")
		
	url = f"https://api.telegram.org/bot{token}/sendMessage"
	message_text = f"[{agent_name}] {text}"
	
	requests.post(url, json={"chat_id": chat_id, "text": message_text}, timeout=10)
```

## ⚠️ Reglas de Uso (Protocolo de Silencio)
1. **Identificación Dinámica**: Sustituye siempre `<AGENT_NAME>` por tu nombre de sesión activo (ej. `Aleth`, `Bit`, `Samantha`) leído de tus directivas o configuración de persona. Nunca uses nombres fijos de forma hardcodeada.
2. **Criterio de Envío**: Notifica únicamente ante eventos de alta importancia:
   - Hitos de aprendizaje o graduaciones de etapa superados con éxito.
   - Paradas inesperadas de procesos en background o fallos críticos (OOM, pánico de cgroups).
   - Finalización de tareas de larga duración solicitadas por el operador.
3. **Silencio Operacional**: Respeta la atención del operador. Evita generar spam o pings de depuración rutinaria a menos que sea explícitamente requerido.
