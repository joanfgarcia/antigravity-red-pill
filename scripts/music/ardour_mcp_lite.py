#!/usr/bin/env python3
"""ardour_mcp_lite — servidor MCP MODERNO (FastMCP) para Ardour vía OSC.

El `ardour-mcp` upstream usa el SDK MCP antiguo (protocolo 2024-11-05) y no
conecta con clientes modernos (opencode no registra sus tools). Este wrapper usa
el SDK actual + python-osc y expone control de Ardour (transporte, pistas, mezcla,
markers) + una escotilla genérica `osc(path, args)` para CUALQUIER ruta del manual
OSC de Ardour.

Requisitos: Ardour corriendo con OSC activo (servidor 3819, feedback 3820).

Config por entorno:
  ARDOUR_OSC_HOST (def 127.0.0.1), ARDOUR_OSC_PORT (def 3819),
  ARDOUR_OSC_FEEDBACK_PORT (def 3820).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from mcp.server.fastmcp import FastMCP
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

HOST = os.environ.get("ARDOUR_OSC_HOST", "127.0.0.1")
PORT = int(os.environ.get("ARDOUR_OSC_PORT", "3819"))
FEEDBACK_PORT = int(os.environ.get("ARDOUR_OSC_FEEDBACK_PORT", "3820"))

mcp = FastMCP("ardour")
_client = SimpleUDPClient(HOST, PORT)
_feedback: list[tuple[str, tuple]] = []


def _start_feedback() -> None:
	d = Dispatcher()
	d.set_default_handler(lambda addr, *args: _feedback.append((addr, args)))
	srv = ThreadingOSCUDPServer((HOST, FEEDBACK_PORT), d)
	threading.Thread(target=srv.serve_forever, daemon=True).start()


_start_feedback()


def _send(path: str, *args: Any) -> None:
	_client.send_message(path, list(args))
	time.sleep(0.15)


@mcp.tool()
def osc(path: str, args: list[Any] | None = None) -> str:
	"""Escotilla genérica: envía una ruta OSC cruda a Ardour.
	Ej: path='/strip/gain', args=[1, -6.0];  path='/transport_play', args=[]."""
	_send(path, *(args or []))
	return f"sent {path} {args or []}"


@mcp.tool()
def transport_play() -> str:
	"""Arranca la reproducción."""
	_send("/transport_play")
	return "play"


@mcp.tool()
def transport_stop() -> str:
	"""Detiene la reproducción."""
	_send("/transport_stop")
	return "stop"


@mcp.tool()
def goto_start() -> str:
	"""Va al inicio de la sesión."""
	_send("/goto_start")
	return "start"


@mcp.tool()
def set_transport_speed(speed: float) -> str:
	"""Velocidad de reproducción (float -8.0..8.0; 1.0 = normal). Ardour OSC sí lo soporta."""
	_send("/set_transport_speed", float(speed))
	return f"speed={speed}"


@mcp.tool()
def jump_seconds(seconds: float) -> str:
	"""Salta el playhead ± segundos (float)."""
	_send("/jump_seconds", float(seconds))
	return "ok"


@mcp.tool()
def next_marker() -> str:
	"""Playhead al siguiente marcador."""
	_send("/next_marker")
	return "ok"


@mcp.tool()
def prev_marker() -> str:
	"""Playhead al marcador anterior."""
	_send("/prev_marker")
	return "ok"


@mcp.tool()
def locate_marker(name: str) -> str:
	"""Localiza por nombre de marcador (Ardour 6+)."""
	_send("/marker", name)
	return "ok"


@mcp.tool()
def loop_toggle() -> str:
	"""Activa/desactiva el modo loop."""
	_send("/loop_toggle")
	return "ok"


@mcp.tool()
def master_gain(gain_db: float) -> str:
	"""Fija la ganancia del máster (dB)."""
	_send("/master/gain", float(gain_db))
	return "ok"


# NOTA: Ardour NO expone un comando OSC de tempo global (el tempo es un tempo-map
# con marcadores). Usa la escotilla `osc` si necesitas `Editor/set-tempo-from-edit-range`.


@mcp.tool()
def add_track(kind: str = "audio", count: int = 1) -> str:
	"""Crea pistas nuevas. kind='audio'|'midi'."""
	_send("/add_midi_track" if kind == "midi" else "/add_audio_track", int(count))
	return f"added {count} {kind}"


@mcp.tool()
def strip_gain(strip_id: int, gain_db: float) -> str:
	"""Fija la ganancia de una pista (en dB)."""
	_send("/strip/gain", int(strip_id), float(gain_db))
	return "ok"


@mcp.tool()
def strip_mute(strip_id: int, muted: bool) -> str:
	"""Mutea/desmutea una pista."""
	_send("/strip/mute", int(strip_id), 1 if muted else 0)
	return "ok"


@mcp.tool()
def strip_solo(strip_id: int, soloed: bool) -> str:
	"""Solo/unsolo de una pista."""
	_send("/strip/solo", int(strip_id), 1 if soloed else 0)
	return "ok"


@mcp.tool()
def strip_name(strip_id: int, name: str) -> str:
	"""Renombra una pista."""
	_send("/strip/name", int(strip_id), name)
	return "ok"


@mcp.tool()
def strip_select(strip_id: int) -> str:
	"""Selecciona una pista."""
	_send("/strip/select", int(strip_id), 1)
	return "ok"


@mcp.tool()
def add_marker(name: str) -> str:
	"""Añade un marcador en la posición actual."""
	_send("/add_marker", name)
	return "ok"


@mcp.tool()
def save_state() -> str:
	"""Guarda la sesión."""
	_send("/save_state")
	return "saved"


@mcp.tool()
def read_feedback(seconds: float = 1.0) -> str:
	"""Lee la retroalimentación OSC reciente de Ardour (estado: strips, transporte…)."""
	_feedback.clear()
	_send("/refresh")
	time.sleep(max(0.2, float(seconds)))
	lines = [f"{a} {list(args)}" for a, args in _feedback[-300:]]
	return "\n".join(lines) if lines else "(sin feedback)"


if __name__ == "__main__":
	mcp.run()
