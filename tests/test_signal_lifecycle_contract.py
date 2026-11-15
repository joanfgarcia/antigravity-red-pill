"""Contrato de ciclo de vida de las señales (2026-11-12).

Un dolor que no se puede enterrar miente para siempre. Medido el 2026-11-12: de
las señales emitidas por los plugins del Janitor, **ocho de nueve** no tenían
camino de entierro — seguían en el tablero (o en el buzón) mucho después de que
la causa desapareciera. Un caso vivo: `memento_stale_distill` saltó a las 08:00
con 16 sesiones, la noche las destiló todas y la señal seguía ahí.

Este test es el guard que faltaba: recorre los emisores del paquete y exige que
cada señal de DOLOR tenga su entierro. Cubre el defecto más común —el emisor que
nace sin entierro—, que es como nacieron los ocho. NO cubre un entierro mal
colocado (un `else` del `try` en vez del `if`): eso lo fijan los tests de
conducta (`test_janitor_signal_burial.py`), porque el código existe y compila.

Reglas (y por qué)

- `signal_type="pain"` en el tablero: requiere `evaporate_signals(<nombre>)`.
  Es un ESTADO (hay N colgados, la cobertura está baja): cuando el estado cesa,
  el aviso debe morir. Sin entierro, el tablero acumula mentiras.
- `signal_type="pain"` + `muted=True`: requiere `resolve_report(<nombre>)`.
  Va al MinionInbox; su entierro es cerrar el reporte, no borrar un punto.
- `signal_type` `status`/`info`: exento. Son INSTANTÁNEAS que se reinyectan en
  cada pase y se sobrescriben por nombre; no son dolores.
- Nombre resuelto solo si es literal o constante asignada (de módulo o local).
  Un nombre construido con f-string no es verificable estáticamente y **no** se
  exime: se ignora aquí y se documenta como límite conocido.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "red_pill"

# Señales de dolor que no pueden enterrarse por diseño (eventos irrepetibles).
# Vacío a propósito: si algún día hace falta una excepción, va aquí CON motivo.
PAIN_EXEMPT: dict[str, str] = {}


def _const_assignments(tree: ast.AST) -> dict[str, str]:
	"""Nombres -> literal para asignaciones `x = "texto"` (módulo o función)."""
	found: dict[str, str] = {}
	for node in ast.walk(tree):
		if not isinstance(node, ast.Assign) or len(node.targets) != 1:
			continue
		target = node.targets[0]
		if not isinstance(target, ast.Name):
			continue
		try:
			value = ast.literal_eval(node.value)
		except Exception:
			continue
		if isinstance(value, str):
			found[target.id] = value
	return found


def _call_name(node: ast.AST) -> str:
	"""Nombre del método invocado (`x.foo(...)` o `foo(...)`)."""
	func = getattr(node, "func", None)
	if isinstance(func, ast.Attribute):
		return func.attr
	if isinstance(func, ast.Name):
		return func.id
	return ""


def _kwarg(node: ast.Call, key: str) -> ast.expr | None:
	for keyword in node.keywords:
		if keyword.arg == key:
			return keyword.value
	return None


def _resolve(node: ast.expr | None, consts: dict[str, str]) -> str | None:
	if isinstance(node, ast.Constant) and isinstance(node.value, str):
		return node.value
	if isinstance(node, ast.Name):
		return consts.get(node.id)
	return None


def _scan() -> tuple[list[tuple[str, str, bool]], set[str], set[str]]:
	"""Devuelve (dolores, entierros de tablero, entierros de buzón)."""
	pains: list[tuple[str, str, bool]] = []
	evaporated: set[str] = set()
	resolved: set[str] = set()
	for path in sorted(SRC.rglob("*.py")):
		if "__pycache__" in str(path):
			continue
		try:
			tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
		except SyntaxError:  # pragma: no cover - un fichero roto lo canta otra suite
			continue
		consts = _const_assignments(tree)
		for node in ast.walk(tree):
			if not isinstance(node, ast.Call):
				continue
			method = _call_name(node)
			if method == "inject_signal":
				name = _resolve(_kwarg(node, "name"), consts)
				if not name:
					continue
				kind = _resolve(_kwarg(node, "signal_type"), consts)
				muted_node = _kwarg(node, "muted")
				muted = isinstance(muted_node, ast.Constant) and muted_node.value is True
				if kind == "pain":
					pains.append((name, str(path.relative_to(SRC.parent.parent)), muted))
			elif method == "evaporate_signals" and node.args:
				name = _resolve(node.args[0], consts)
				if name:
					evaporated.add(name)
			elif method == "resolve_report" and node.args:
				name = _resolve(node.args[0], consts)
				if name:
					# El inbox usa `event_id=f"signal_{name}"` (memory.inject_signal):
					# se normaliza para que el entierro se lea por nombre de señal.
					resolved.add(name.removeprefix("signal_"))
			elif method == "bury_signal" and node.args:
				# API del contrato: `bury_signal(name, muted=…)` entierra por nombre.
				name = _resolve(node.args[0], consts)
				if not name:
					continue
				muted_node = _kwarg(node, "muted")
				if isinstance(muted_node, ast.Constant) and muted_node.value is True:
					resolved.add(name)
				else:
					evaporated.add(name)
	return pains, evaporated, resolved


def test_toda_senal_de_dolor_tiene_su_entierro():
	"""El dolor nace con su entierro, o no nace."""
	pains, evaporated, resolved = _scan()
	assert pains, "el escáner no encontró emisores: ¿cambió la API de señales?"

	huerfanos = []
	for name, where, muted in pains:
		if name in PAIN_EXEMPT:
			continue
		if muted and name not in resolved:
			huerfanos.append(f"{name} (muted → falta resolve_report)  · {where}")
		elif not muted and name not in evaporated:
			huerfanos.append(f"{name} (tablero → falta evaporate_signals)  · {where}")

	assert not huerfanos, (
		"Señales de DOLOR sin camino de entierro. Un dolor que no puede morir miente "
		"para siempre (2026-11-12: 8 de 9 plugins del Janitor estaban así):\n  - "
		+ "\n  - ".join(huerfanos)
	)


def test_el_escanner_ve_las_senales_conocidas():
	"""Anti-falso-verde: si el AST deja de resolver nombres, este test lo delata."""
	pains, evaporated, resolved = _scan()
	nombres = {name for name, _, _ in pains}
	# Ancla: una del tablero (hub_synthesis_failed, con nombre en variable local)
	# y una silenciada (memento_stale_distill).
	assert "hub_synthesis_failed" in nombres, f"no resolvió nombres locales: {sorted(nombres)[:8]}"
	assert "memento_stale_distill" in nombres, "perdió las señales muted"
	assert "hub_synthesis_failed" in evaporated
	assert "memento_stale_distill" in resolved, "el entierro del buzón no se está viendo"
