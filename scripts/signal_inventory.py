#!/usr/bin/env python3
"""Inventario de señales del auditor (RFC-OBS-005 §4.1).

Los nombres de señal son un HECHO del código, no una preferencia: viven junto al
emisor (`SEGMENT_SIGNAL_NAMES`, `REPO_STEP_SIGNAL_NAMES` y los `type="..."` de los
plugins). Este script los vuelca al YAML para que el Operador lo vea todo en un
sitio, sin que la separación por módulos se rompa.

Uso:
	scripts/signal_inventory.py --write    # regenera el bloque del YAML
	scripts/signal_inventory.py --check    # exit 1 si el YAML está desfasado

El bloque va entre marcadores; lo de fuera se respeta byte a byte.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from red_pill.metabolism.auditor import (  # noqa: E402
	REPO_STEP_SIGNAL_NAMES,
	SEGMENT_SIGNAL_NAMES,
	signal_name_for,
)

PROFILES = ROOT / "configs" / "signals" / "signal_profiles.yaml"
PLUGINS_DIR = ROOT / "src" / "red_pill" / "metabolism" / "sentinel_plugins"
BEGIN = "# BEGIN GENERATED: signal_inventory (scripts/signal_inventory.py --write)"
END = "# END GENERATED: signal_inventory"


def plugin_inventory() -> dict[str, list[str]]:
	"""Nombres que puede emitir cada plugin, derivados de sus `type="..."`."""
	out: dict[str, list[str]] = {}
	for path in sorted(PLUGINS_DIR.glob("*.py")):
		types = set(re.findall(r'type="([a-z_]+)"', path.read_text(encoding="utf-8")))
		if types:
			out[path.stem] = sorted(signal_name_for(t) for t in types)
	return out


def render_block() -> str:
	lines = [BEGIN, "inventory:", "  # Generado desde los emisores; no editar a mano.", "  segments:"]
	for segment in sorted(SEGMENT_SIGNAL_NAMES):
		names = ", ".join(sorted(SEGMENT_SIGNAL_NAMES[segment]))
		lines.append(f"    {segment}: [{names}]")
	steps = [f"{step}: {name}" for step, name in sorted(REPO_STEP_SIGNAL_NAMES.items())]
	lines.append("  repo_steps: {" + ", ".join(steps) + "}")
	lines.append("  plugins:")
	for plugin, names in plugin_inventory().items():
		lines.append(f"    {plugin}: [{', '.join(names)}]")
	lines.append(END)
	return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
	if BEGIN in text and END in text:
		start = text.index(BEGIN)
		end = text.index(END) + len(END)
		return text[:start] + block + text[end:]
	anchor = "\nsignals:"
	if anchor in text:
		return text.replace(anchor, "\n" + block + "\n" + anchor, 1)
	return text.rstrip("\n") + "\n\n" + block + "\n"


def main() -> int:
	parser = argparse.ArgumentParser(description="Inventario de señales (RFC-OBS-005)")
	parser.add_argument("--write", action="store_true", help="regenera el bloque del YAML")
	parser.add_argument("--check", action="store_true", help="falla si el YAML está desfasado")
	args = parser.parse_args()
	if not (args.write or args.check):
		parser.error("indica --write o --check")

	current = PROFILES.read_text(encoding="utf-8")
	block = render_block()
	updated = replace_block(current, block)

	if args.check:
		if current.strip() != updated.strip():
			print("[signal_inventory] el bloque `inventory:` está desfasado; corre --write", file=sys.stderr)
			return 1
		print("[signal_inventory] YAML al día")
		return 0

	PROFILES.write_text(updated, encoding="utf-8")
	print(f"[signal_inventory] escrito {PROFILES.relative_to(ROOT)}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
