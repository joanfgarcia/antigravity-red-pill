"""Atribución de hablante en el pipeline de memoria (USER / PEER / TOOL).

El buffer rápido etiquetaba como `USER:` *cualquier* prompt:

    text = f"USER: {prompt}\\n\\n{role.upper()}: {response}"

y el prompt del destilador define `USER:` como «habló el Operador». Consecuencia:
un mensaje de otra sesión del mismo agente —o un volcado de herramienta— se
archiva como una frase del Operador. Eso produce dos daños a la vez:

- **Autoridad fabricada**: una conversación entre piernas del mismo alma queda
  registrada como una orden.
- **Hecho falso firmado**: si el dato del par era erróneo, el error queda
  atribuido al Operador y ningún chequeo posterior lo pone en duda.

Caso real (2026-10-27), archivado como «Usuario»:

    ［MENSAJE ENTRE ALMAS · no es del Operador · DE 01a17f58 Aleth-GLM …］

El sobre declaraba por escrito que no era del Operador y el pipeline lo ignoró.

El sobre varía entre piernas (corchetes ASCII o de ancho completo, a veces
envuelto en comillas por el arnés), así que la detección no se apoya en el
corchete: busca el marcador en la cabecera, sin distinguir mayúsculas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Etiquetas que viajan al texto que consume el destilador.
OPERATOR = "USER"
PEER = "PEER"
TOOL = "TOOL"

# Marcador del sobre entre almas. Presente en ASCII y en ancho completo.
_PEER_MARKER = "MENSAJE ENTRE ALMAS"

# Cabeceras de volcado de herramienta (ASCII y ancho completo).
_TOOL_MARKERS = ("[TOOL RESULT", "［TOOL RESULT", "[TOOL USE", "［TOOL USE", "TOOL OUTPUT")

# Basura de envoltura que añaden los arneses: comillas, espacios, corchetes.
_LEADING_NOISE = " \t\r\n\"'«»“”()[]［］<>"

# Para las cabeceras de herramienta los corchetes son parte del marcador: no se
# recortan antes de comparar.
_LEADING_QUOTES = " \t\r\n\"'«»“”"

# `DE 01a18156 Aleth …` — el emisor. El receptor va como `A 01a186e6`, así que
# exigir el `DE` delante es lo que evita capturar el destinatario.
_PEER_ID = re.compile(r"\bDE\s+([0-9a-f]{8})\b", re.IGNORECASE)

# Cuántos caracteres de cabecera se inspeccionan. El sobre completo (con
# hilo/verbo/tag) cabe de sobra; más allá es cuerpo y no debe clasificar.
_HEAD_CHARS = 400


@dataclass(frozen=True)
class Speaker:
	"""Quién habló en un turno y si su contenido puede leerse como instrucción."""

	label: str
	peer_id: str | None = None
	is_instruction: bool = True

	@property
	def is_peer(self) -> bool:
		return self.label == PEER

	@property
	def is_tool(self) -> bool:
		return self.label == TOOL


def classify_prompt(prompt: str | None) -> Speaker:
	"""Clasifica el prompt de un turno como OPERATOR, PEER o TOOL.

	Fail-safe hacia el Operador: un prompt normal no cambia de etiqueta. Sólo se
	reclasifica cuando la cabecera lo declara de forma explícita.

	El sobre tiene que **abrir** el turno, no aparecer mencionado en el cuerpo.
	Sin esa restricción, cualquier turno que hable del mecanismo se archivaría
	como mensaje entre almas — y ocurre: al consultar la base de opencode salen
	mensajes del propio agente que lo citan a mitad de frase.
	"""
	text = prompt or ""

	bare = text.lstrip(_LEADING_QUOTES)
	upper_bare = bare.upper()
	for marker in _TOOL_MARKERS:
		if upper_bare.startswith(marker.upper()):
			return Speaker(TOOL, is_instruction=False)

	head = text.lstrip(_LEADING_NOISE)[:_HEAD_CHARS]
	if head.upper().startswith(_PEER_MARKER):
		match = _PEER_ID.search(head)
		return Speaker(PEER, match.group(1).lower() if match else None, is_instruction=False)

	return Speaker(OPERATOR)


def render_turn(prompt: str, response: str, response_role: str = "assistant") -> str:
	"""Construye el par turno/respuesta con la etiqueta correcta del hablante.

	Es el único sitio que decide el prefijo; cualquier consumidor (destilador,
	chunker, maintenance) ve el mismo texto.
	"""
	speaker = classify_prompt(prompt)
	return f"{speaker.label}: {prompt}\n\n{(response_role or 'assistant').upper()}: {response}"
