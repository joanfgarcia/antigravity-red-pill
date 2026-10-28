"""Runtime JS para los tests de artefactos del arnés (opencode/pi).

Por qué existe este módulo
--------------------------
Los seeds JS (plugin de opencode, extensión de pi) se ejecutan **en producción**
dentro del runtime embebido del arnés. Verificado con una sonda el 2026-10-28:
opencode v2 ejecuta los plugins con **Bun 1.4.4 embebido** en su binario
(`opencode-cli`), NO con el `bun` del sistema ni con Node (reporta
`bunVersion: 1.4.4`, `nodeVersion: 26.3.0` como capa de compat, `argv0: "bun"`).

Los tests, en cambio, invocaban el `bun` del **sistema** (`shutil.which("bun")`),
que puede no existir (en CI **no** se instala → los tests se saltaban **mudos**,
cobertura cero sin avisar) o ser otra versión (el sistema tenía 1.3.6 vs 1.4.4
embebido). Ese es el fallo que este módulo cierra:

1. **Selección de runtime por preferencia y override** (`REDPILL_JS_RUNTIME`):
   - `opencode-embedded`: el runtime del arnés si se puede localizar (futuro).
   - `bun`: el del sistema.
   - `node`: último recurso (los harness de test usan `bun:sqlite`, así que Node
     sólo sirve para los artefactos que no dependan de esa API).
2. **Skip RUIDOSO**: si no hay ninguno, se marca `xfail(strict=False)` con motivo
   visible en el reporte, no un `skip` silencioso. Un fail-open invisible es peor
   que un test que no corre: al menos así se ve.

Contrato del harness de test: los ficheros `harness.mjs` que ejercitan el plugin
de opencode importan `bun:sqlite` (API que sólo existe en Bun). Por eso el
runtime por defecto es Bun, y Node queda como último recurso documentado.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Env para forzar un runtime concreto en local/CI (p.ej. "node", "bun").
ENV_RUNTIME = "REDPILL_JS_RUNTIME"
# Env para apuntar al binario del arnés (opencode) y probar su runtime embebido.
ENV_HARNESS_BIN = "REDPILL_HARNESS_BIN"


@dataclass(frozen=True)
class JsRuntime:
	"""Runtime JS disponible: comando + etiqueta + capacidades."""

	kind: str  # "bun" | "node" | "opencode-embedded"
	cmd: list[str]  # p.ej. ["bun"] o ["node"]
	version: str
	has_bun_sqlite: bool
	label: str

	def run(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
		"""Ejecuta el runtime con args (p.ej. el path del harness .mjs)."""
		return subprocess.run([*self.cmd, *args], **kwargs)


def _probe(cmd: list[str], kind: str) -> Optional[JsRuntime]:
	"""Sondea un binario: ¿existe? ¿versión? ¿tiene `bun:sqlite`?

	Sonda determinista con un script efímero; cualquier fallo → None (no lanza).
	"""
	if not cmd or shutil.which(cmd[0]) is None:
		return None
	# Un solo script que reporta versión + si `bun:sqlite` resuelve.
	script = (
		'const v = (typeof Bun !== "undefined") ? ("bun " + Bun.version) '
		': ("node " + (process.versions && process.versions.node));'
		'let b = false; try { await import("bun:sqlite"); b = true; } catch (_) {}'
		'console.log(JSON.stringify({ v, b }));'
	)
	try:
		res = subprocess.run(
			[*cmd, "-e", script],
			capture_output=True,
			text=True,
			timeout=30,
		)
	except Exception:
		return None
	if res.returncode != 0:
		return None
	import json

	try:
		data = json.loads(res.stdout.strip().splitlines()[-1])
	except Exception:
		return None
	version = str(data.get("v") or "").strip()
	has = bool(data.get("b"))
	return JsRuntime(kind=kind, cmd=cmd, version=version, has_bun_sqlite=has, label=f"{kind} ({version})")


def find_js_runtime(*, require_bun_sqlite: bool = True, require_kind: str | None = None) -> Optional[JsRuntime]:
	"""Mejor runtime JS que cumple TODAS las restricciones, o None.

	Restricciones se cumplen o no hay runtime: no se devuelve un runtime que no
	las satisface "por si acaso" (eso escondía un fallo más tarde). Orden de
	preferencia: override por env → bun del sistema → node del sistema.

	El runtime embebido del arnés no es invocable hoy (`opencode` no expone un
	`eval` de JS: probado, interpreta el argumento como cwd), así que la
	equivalencia con producción se aproxima prefiriendo **Bun**, que es el motor
	que el arnés embebe (verificado: Bun 1.4.4 vía sonda 2026-10-28).
	"""
	forced = str(os.getenv(ENV_RUNTIME) or "").strip().lower()
	if forced == "node":
		candidates = [(["node"], "node")]
	elif forced == "bun":
		candidates = [(["bun"], "bun")]
	else:
		candidates = [(["bun"], "bun"), (["node"], "node")]

	for cmd, kind in candidates:
		rt = _probe(cmd, kind)
		if rt is None:
			continue
		if require_kind is not None and rt.kind != require_kind:
			continue
		if require_bun_sqlite and not rt.has_bun_sqlite:
			continue  # Node no tiene `bun:sqlite`
		return rt
	return None


def runtime_unavailable_reason() -> str:
	"""Motivo legible para marcar el test como no ejecutable (skip ruidoso)."""
	return (
		"sin runtime JS válido: no hay `bun` ni `node` en PATH "
		f"(fuerza uno con {ENV_RUNTIME}=bun|node). "
		"EN CI esto significa que el artefacto JS NO se está validando."
	)


def needs_js_runtime(*, require_bun_sqlite: bool = True, require_kind: str | None = None):
	"""Decorador: XFAIL ruidoso SOLO en los tests que de verdad ejecutan JS.

	No usar `pytestmark` a nivel de módulo: marcaría también los tests que solo
	leen el seed y comparan texto (que no necesitan runtime y deben pasar
	siempre). Un xfail ahí sería un falso negativo silencioso.
	"""
	import pytest

	rt = find_js_runtime(require_bun_sqlite=require_bun_sqlite, require_kind=require_kind)
	return pytest.mark.xfail(rt is None, reason=runtime_unavailable_reason(), strict=False)


def js_runtime_root() -> Path:
	"""Directorio de trabajo para sondas (scratch temporal, nunca el repo)."""
	base = Path(os.getenv("TMPDIR") or "/tmp") / "opencode"
	base.mkdir(parents=True, exist_ok=True)
	return base
