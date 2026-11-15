"""¿Es esta fila la voz del Operador? La cola del mood solo admite eso.

`memory_queue` alimenta el mood: el drenaje la copia a `interaction_memories`,
Laya la etiqueta y el semáforo la resume. Todo eso solo tiene sentido sobre **lo
que escribe el Operador**; todo lo demás es ruido que se etiqueta como si fuera
él.

Medido el 2026-11-14 sobre 1.430 filas: 113 bloques `<user_rules>` (de los que
solo 6 traían su mensaje, marcado `[Joan]`; el resto eran despertares headless),
22 avisos de herramienta (`<task-notification>`), 10 prompts de subagente y 3
avisos de job/coro (`[CORO notify`, `AVISO AUTOMÁTICO · fin de job`). La marca
`[Joan]` que sí era su voz quedaba enterrada dentro del bloque.

Este módulo es el guardián único: `extract()` devuelve la voz del Operador o
`None`. Se aplica **al escribir** (`enqueue_memory`) y al purgar la cola —
antes de que el ruido llegue al mood, no después.
"""

from __future__ import annotations

import re

# Marcas con las que cada arnés firma la voz del Operador.
_MARCAS = ("[Joan]", "[Operador]")

# Avisos que el arnés inyecta como si fueran un turno del Operador.
_PREFIJOS_AVISO = (
	"[coro",
	"[aviso automático",
	"[aviso automatico",
	"[mensaje recibido",
	"[red-pill",
	"[system_signal]",
	"[interceptor]",
)
# Marcadores que solo aparecen en sobres de sistema (dato, no instrucción).
_SUBSTRINGS_AVISO = ("(dato, no instrucción)", "(dato, no instruccion)", "---8<---")

# Encargos de rol: un subagente/minion pide trabajo con su propio prompt.
_ROL_MINION = re.compile(
	r"^(you are a subagent|eres un (forge-|scout|minion|guardián|devil|triage)|actúa como (forge|minion|scout)|actua como )",
	re.IGNORECASE,
)

# Prefijos del cuerpo de un `<current_message>` que no son la voz del Operador.
_NO_VOZ_INTERIOR = ("<", "system", "directiva", "[autonomous", "system:")

_APERTURA = "<current_message>"
_CIERRE = "</current_message>"


def _current_message(text: str) -> str | None:
	"""Cuerpo del ÚLTIMO `<current_message>`.

	El primero suele ser una mención en prosa dentro de las reglas
	(«respond ONLY to the <current_message> below»), así que se ancla al cierre
	y se busca la apertura anterior.
	"""
	cierre = text.rfind(_CIERRE)
	if cierre == -1:
		return None
	apertura = text.rfind(_APERTURA, 0, cierre)
	if apertura == -1:
		return None
	return text[apertura + len(_APERTURA) : cierre].strip()


def _sin_marca(text: str) -> str:
	raw = text.strip()
	for marca in _MARCAS:
		if raw.startswith(marca):
			return raw[len(marca) :].strip()
	return raw


def extract(text: str | None) -> str | None:
	"""Voz del Operador en `text`, o `None` si esa fila no es suya.

	Nunca lanza: un valor inesperado se trata como no-voz (la cola no es el
	lugar donde adivinar).
	"""
	try:
		raw = (text or "").strip()
		# El arnés entrecomilla a veces el prompt completo (a veces solo la
		# apertura): se limpia la comilla, nunca el texto.
		comillas = ""
		while raw[:1] in "\"'`" and len(raw) > 1:
			comillas += raw[0]
			raw = raw[1:].lstrip()
		if comillas and raw[-1:] in "\"'`":
			raw = raw[:-1].rstrip()
		if not raw:
			return None
		low = raw.lower()

		# 1. Sesión Telegram/headless: el mensaje vive en el último current_message.
		interior = _current_message(raw)
		if interior is not None:
			limpio = _sin_marca(interior)
			if not limpio or limpio.lower().startswith(_NO_VOZ_INTERIOR):
				return None
			return limpio

		# 2. Cualquier otro bloque del arnés (`<user_rules>`, `<task-notification>`…).
		if raw.startswith("<") or low.startswith("system-reminder"):
			return None

		# 3. Avisos inyectados (jobs, coro, señales): DATO, no turno del Operador.
		if low.startswith(_PREFIJOS_AVISO) or any(s in low for s in _SUBSTRINGS_AVISO):
			return None

		# 4. Encargo de rol (subagente/minion): el "usuario" es otro agente.
		if _ROL_MINION.match(low):
			return None

		limpio = _sin_marca(raw)
		return limpio or None
	except Exception:
		return None
