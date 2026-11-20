"""Resolver de perfiles: `rol × capacidad × egress` → bundle (RFC-HARNESS-001 · P3b).

Un perfil no es una lista de skills: es la combinación de **qué hace** (rol), **con
qué** (capacidad) y **qué puede tocar fuera** (egress). El bundle resultante es lo
que consumen los inyectores (`scripts/inject/*`) y el sandbox.

Dos ejes ortogonales que antes mezclábamos: un 9B y un frontier en el mismo rol
necesitan *plomería* distinta (ventana, superficie de tools, identidad) pero **las
mismas reglas**; un reviewer y un worker con el mismo modelo necesitan la misma
plomería y **reglas distintas**.

La **unidad de experimento** es la tupla `(kernel ref, perfil, modelo)`: el resto
se deriva de aquí, así que dos ejecuciones son comparables.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "configs" / "profiles"


class ProfileError(ValueError):
	"""Combinación de perfil desconocida o incoherente."""


@dataclass
class Bundle:
	role: str
	capability: str
	egress: str
	purpose: str = ""
	skills: List[str] = field(default_factory=list)
	skills_library: List[str] = field(default_factory=list)
	rules_blocks: List[str] = field(default_factory=list)
	boot_card: str = ""
	surface: str = "full"
	identity_mode: str = "full"
	identity_max_tokens: int = 0
	tools_native: List[str] = field(default_factory=list)
	limits: Dict[str, Any] = field(default_factory=dict)
	window: int = 0
	kv: Optional[str] = None
	network: str = "local"
	secrets: str = "none"
	gates: List[str] = field(default_factory=list)
	notes: str = ""

	def to_dict(self) -> Dict[str, Any]:
		return asdict(self)


def _load(root: Path, kind: str, name: str) -> Dict[str, Any]:
	path = root / kind / f"{name}.yaml"
	if not path.is_file():
		raise ProfileError(f"no existe {kind}/{name}.yaml en {root}")
	data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
	if not isinstance(data, dict):
		raise ProfileError(f"{kind}/{name}.yaml no es un mapa")
	return data


def available(root: Optional[Path] = None) -> Dict[str, List[str]]:
	base = root or DEFAULT_ROOT
	return {kind: sorted(p.stem for p in (base / kind).glob("*.yaml")) for kind in ("roles", "capabilities", "egress")}


def resolve(
	role: str,
	capability: str,
	egress: str,
	*,
	root: Optional[Path] = None,
) -> Bundle:
	"""Resuelve el bundle. Falla ruidosamente si la combinación no existe."""
	base = root or DEFAULT_ROOT
	role_d = _load(base, "roles", role)
	cap_d = _load(base, "capabilities", capability)
	eg_d = _load(base, "egress", egress)

	blocked = set(eg_d.get("skills_blocked") or [])
	wanted = [s for s in (role_d.get("skills_install") or []) if s not in blocked]
	budget = int(cap_d.get("skills_budget") or len(wanted))
	skills = wanted[:budget]
	library = wanted[budget:]

	limits = {**(role_d.get("limits") or {})}
	if cap_d.get("compact_at") is not None:
		limits.setdefault("compact_at", cap_d["compact_at"])

	return Bundle(
		role=str(role_d.get("id") or role),
		capability=str(cap_d.get("id") or capability),
		egress=str(eg_d.get("id") or egress),
		purpose=str(role_d.get("purpose") or ""),
		skills=skills,
		skills_library=library,
		rules_blocks=list(role_d.get("rules_blocks") or []),
		boot_card=str(role_d.get("boot_card") or role),
		surface=str(cap_d.get("surface") or "full"),
		identity_mode=str(cap_d.get("identity_mode") or "full"),
		identity_max_tokens=int(cap_d.get("identity_max_tokens") or 0),
		tools_native=list(cap_d.get("tools_native") or []),
		limits=limits,
		window=int(cap_d.get("window") or 0),
		kv=cap_d.get("kv"),
		network=str(eg_d.get("network") or "local"),
		secrets=str(eg_d.get("secrets") or "none"),
		gates=list(role_d.get("gates") or []),
		notes=str(cap_d.get("notes") or ""),
	)


def describe(bundle: Bundle) -> str:
	"""Resumen legible (para `--print` de los inyectores y para los reportes)."""
	lines = [
		f"perfil {bundle.role} × {bundle.capability} × {bundle.egress}",
		f"  ventana {bundle.window:,} · identidad {bundle.identity_mode} (≤{bundle.identity_max_tokens} tok) · superficie {bundle.surface}",
		f"  skills instaladas ({len(bundle.skills)}): {', '.join(bundle.skills) or '—'}",
	]
	if bundle.skills_library:
		lines.append(f"  biblioteca ({len(bundle.skills_library)}): {', '.join(bundle.skills_library)}")
	lines.append(f"  reglas: {', '.join(bundle.rules_blocks) or '—'}")
	lines.append(f"  red {bundle.network} · secretos {bundle.secrets} · límites {bundle.limits}")
	return "\n".join(lines)
