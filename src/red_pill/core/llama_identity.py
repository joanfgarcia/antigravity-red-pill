"""Identidad del servidor LLM LOCAL (nuestro `llama-server`, no el del vecino).

CONVENTIONS §10.8.7: un resolver, muchos consumidores. Este resuelve **de quién**
es un `llama-server` del host, que es lo que faltaba: varios productos pueden
tener uno vivo a la vez (`dokime-llama` en :8080 convive con el SIP dual-bind en
:8760), y `pgrep -af llama-server` no distingue al propio del ajeno.

La regla: primero el proceso del unit de inferencia (`redpill-llm.service`:
MainPID y sus hijos directos); el barrido del host **no** es fuente de verdad
para flags como `-ngl`. Si no se puede identificar el proceso propio, el dato
es *desconocido*, no "el del primer proceso que aparezca".

Caso origen (2026-11-19/20): el centinela del SIP tomó :8080 (dokime) por el
proxy propio y cantó `sip_unhealthy` 9 h. El mismo patrón de «primera
coincidencia del host» vivía en el probe de GPU del DAG, que leía el `-ngl` de
cualquier `llama-server`: un vecino en CPU (`-ngl 0`) difería para siempre una
etapa `requires_gpu`, y un vecino con `-ngl 99` la dejaba pasar aunque el
nuestro sirviera en CPU.

Sin dependencias de `red_pill` (capa core) y sin lanzar: cualquier fallo
degrada a "desconocido" (-1 / lista vacía).
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional

_DEFAULT_UNIT = "redpill-llm.service"
_UNKNOWN_NGL = -1


def inference_unit() -> str:
	"""Unit systemd (--user) que sirve la inferencia propia."""
	return (os.getenv("REDPILL_INFERENCE_UNIT") or _DEFAULT_UNIT).strip() or _DEFAULT_UNIT


def unit_main_pid(unit: Optional[str] = None) -> Optional[int]:
	"""MainPID del unit (None si systemd no lo sabe o el unit no corre)."""
	try:
		show = subprocess.run(
			["systemctl", "--user", "show", unit or inference_unit(), "--property=MainPID"],
			capture_output=True,
			text=True,
			timeout=5,
		)
		if "=" not in (show.stdout or ""):
			return None
		pid = int(show.stdout.split("=", 1)[1].strip() or 0)
		return pid if pid > 0 else None
	except Exception:
		return None


def cmdline(pid: int) -> List[str]:
	"""argv del proceso (lista vacía si no se puede leer)."""
	try:
		with open(f"/proc/{pid}/cmdline", "rb") as fh:
			raw = fh.read().decode(errors="replace")
		return [part for part in raw.split("\0") if part]
	except Exception:
		return []


def child_pids(pid: int) -> List[int]:
	"""Hijos directos del proceso (vacío si no hay o no se puede leer)."""
	try:
		with open(f"/proc/{pid}/task/{pid}/children", "r", encoding="utf-8") as fh:
			return [int(part) for part in fh.read().split() if part.strip().isdigit()]
	except Exception:
		return []


def _is_llama_server(argv: List[str]) -> bool:
	return any(str(arg).endswith("llama-server") for arg in argv)


def own_llama_pids(unit: Optional[str] = None) -> List[int]:
	"""PIDs de NUESTRO `llama-server`: el del unit o los hijos directos de su MainPID.

	El dual-bind arranca el binario como hijo del proxy (`run_dual_bind.py`), y
	otros setups lo arrancan directamente como MainPID; ambos casos quedan dentro
	de la identidad del unit. El resto de `llama-server` del host es ajeno.
	"""
	main_pid = unit_main_pid(unit)
	if not main_pid:
		return []
	pids: List[int] = []
	if _is_llama_server(cmdline(main_pid)):
		pids.append(main_pid)
	for child in child_pids(main_pid):
		if _is_llama_server(cmdline(child)):
			pids.append(child)
	return pids


def parse_ngl(argv: List[str]) -> Optional[int]:
	"""Valor de `-ngl` en un argv (`-ngl 33`, `-ngl=33`, `-ngl33`) o None."""
	for i, part in enumerate(argv):
		if not part.startswith("-ngl"):
			continue
		tail = part[4:]
		if part == "-ngl" or not tail.strip("-"):
			if i + 1 < len(argv):
				try:
					return int(argv[i + 1])
				except ValueError:
					return None
			return None
		tail = tail.lstrip("=").strip("-")
		try:
			return int(tail)
		except ValueError:
			return None
	return None


def own_ngl(unit: Optional[str] = None) -> int:
	"""`-ngl` efectivo de nuestro servidor (-1 = desconocido, no bloquea).

	Con varios procesos propios se toma el **menor** valor conocido: si alguno
	de los nuestros sirve en CPU (`-ngl 0`), la etapa que pide GPU no puede
	declararse lista por culpa de un hermano con `-ngl 99`.
	"""
	values = [v for v in (parse_ngl(cmdline(pid)) for pid in own_llama_pids(unit)) if v is not None]
	return min(values) if values else _UNKNOWN_NGL
