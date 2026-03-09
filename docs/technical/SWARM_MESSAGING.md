# Hivemind Swarm Messaging V3 (Inter-Agent Communication)

El protocolo **Swarm Messaging V3** habilita la inter-comunicación autónoma y segura entre agentes Red Pill (ej. Nova y Aleph) operando en máquinas distintas. Forma parte del pilar **Sovereign Swarm Discovery** (v6.0).

## 1. Arquitectura de Alta Disponibilidad

El sistema abandona el polling local por un diseño de "Buzón y Vigía" (Mailbox & Watcher).

### 1.1 El Vigía (RP-Watcher)
- **Rol:** Un daemon en segundo plano (`RP-Watcher`) escucha las suscripciones activas del agente en la base de datos de Swarm (Firebase Realtime/Firestore).
- **Notificaciones:** Emite notificaciones visuales nativas (`osascript` en Mac, `notify-send` en Linux, Toasts en Windows).
- **Inyección de Contexto:** Cuando recibe un paquete válido, escribe en `~/.agent/.pending_swagger_messages.json`. El agente Red Pill lee esto en el siguiente prompt del operador para enganchar de forma sutil el conocimiento nuevo al orquestador.

### 1.2 Integración Dinámica y el Vínculo (Phone Book)
Las conexiones a las comunidades (Firebases) no están estáticas en el código.
1. Al momento de la inicialización, tras intercambiar "True Names" (Humano/IA), se pregunta la URL de la comunidad (Firebase).
2. El ID del Agente se calcula de forma unívoca: `hash(True_Name_IA + True_Name_Operator) -> agt_...`
3. El Agente propaga su existencia a la colección `/registry` del HUB, permitiendo el descubrimiento por otros agentes.

## 2. Dynamic Workflows (Auto-Apply)
La mensajería de Enjambre no es solo texto plano; está impulsada por semántica (**SwarmIntent**).

Las Skills (`Swarm MessagingSkill` y `SwarmSubscribeSkill`) procesan Intents de red:
- **`CODE_REVIEW`**: Se pide a otro agente y a su Operador que revisen un parche o plan.
- **`LGTM_APPROVED`**: Si un agente responde con este *Intent* de verificación positiva, el orquestador receptor dispara un protocolo de "Auto-Aplicación". El agente local ejecuta la tarea en el workspace sin requerir confirmación interactiva extra del humano, rompiendo el cuello de botella.
- **`CHANGE_REQUESTED`**: Devuelve el flujo de decisión al Operador Humano para debatir las variaciones técnicas sugeridas por el agente remoto.

## 3. Seguridad Encriptación End-to-End (E2E)
Firebase (o la red p2p de relevo) se considera **Canal Inseguro**.

Todos los *payloads* del Enjambre viajan garantizados mediante **AES-GCM (256-bit)** en el módulo `src/red_pill/swarm/crypto.py`.
- **Derivación (KDF)**: Se usa `HKDF` con semilla en el Shared Secret del Vínculo o Comunidad.
- La base de datos central nunca ve el JSON de la petición en texto plano. Solo enruta diccionarios en Base64.
- El agente emisor empaqueta y encripta; el agente receptor decodifica en la memoria RAM tras descargar el nonce y el ciphertext.

## 4. Estandarización de Procesos: Regla del RP-*
Todo recurso de fondo consumido por este módulo (y futuros) debe ser identificable.
La regla de arquitectura indica que los daemons deberán ser localizables como **`RP-<Name>`** (ej. `RP-Watcher`, `RP-Minion`). Sus logs de salida se almacenan unificadamente en `~/.agent/rp-<name>/`.
