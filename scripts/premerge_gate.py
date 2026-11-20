"""Puerta previa al merge: todo lo que hay que ver en verde antes de tocar `next`.

Cuatro puertas, en este orden, y **ninguna se salta sin decirlo**:

1. **Estilo** — `ruff check` sobre `src/`, `scripts/` y `tests/`.
2. **Suite** — `pytest tests/` completa.
3. **Capacidades** — las 15 tools por el transporte real, dentro del sandbox
	(`capability_bench.py`), incluidas las alcanzables por `redpill_call` (la
	prueba del perfil `gateway`). Si el sandbox está apagado, la puerta se marca
	`SKIP` con aviso: un merge sin esta puerta es un merge sin probar el arnés.
4. **Presupuesto** — coste de arranque `full` vs `gateway`. El objetivo es que
	`gateway` ahorre al menos el 50 %; si no, algo ha engordado una tool.

Uso:
	python scripts/premerge_gate.py                 # ritual completo
	python scripts/premerge_gate.py --skip-suite    # iterar rápido
	python scripts/premerge_gate.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = "dokime"
GATEWAY_MIN_SAVING = 0.50


def _run(cmd: List[str], env_prefix: List[str] | None = None, timeout: int = 2400) -> tuple[int, str]:
	if env_prefix:
		cmd = env_prefix + cmd
	proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
	return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def gate_style() -> Dict[str, Any]:
	rc, out = _run([sys.executable, "-m", "ruff", "check", "src/", "scripts/", "tests/"])
	return {"gate": "estilo", "ok": rc == 0, "detail": out.strip().splitlines()[-1] if out.strip() else ""}


def gate_suite() -> Dict[str, Any]:
	rc, out = _run([sys.executable, "-m", "pytest", "tests/", "-q", "--timeout=300"], timeout=3600)
	tail = [ln for ln in out.strip().splitlines() if re.search(r"\d+ (passed|failed)", ln)]
	return {"gate": "suite", "ok": rc == 0, "detail": tail[-1] if tail else out.strip().splitlines()[-1:] or ""}


def gate_capabilities(allow_no_sandbox: bool, sandbox: str = SANDBOX) -> Dict[str, Any]:
	ps = subprocess.run(["podman", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, check=False)
	if sandbox not in (ps.stdout or "").split():
		return {
			"gate": "capacidades",
			"ok": allow_no_sandbox,
			"skipped": True,
			"detail": "sandbox apagado: capability_bench NO ejecutado",
		}
	# El asignado de env va ANTES de `timeout`: `timeout 600 PYTHONPATH=…` no
	# ejecuta nada (rc=127) y la puerta lo cazó como FALLA — que es lo correcto.
	inner = "PYTHONPATH=/src/red-pill/src timeout 600 /opt/py/bin/python /src/red-pill/scripts/capability_bench.py --via-redpill-call"
	rc, out = _run(["podman", "exec", "-w", "/srv/dokime/workspace", sandbox, "sh", "-lc", inner], timeout=900)
	summary = ""
	for ln in reversed(out.strip().splitlines()):
		if ln.startswith('{"tools"'):
			summary = ln
			break
	try:
		data = json.loads(summary) if summary else {}
	except Exception:  # noqa: BLE001
		data = {}
	fails = data.get("fails") or []
	return {
		"gate": "capacidades",
		"ok": rc == 0 and not fails,
		"detail": f"{data.get('tools', '?')}/{data.get('expected', '?')} tools · fallos: {fails or 'ninguno'}",
	}


def gate_hook_vivo() -> Dict[str, Any]:
	"""El backend EN MARCHA, no sólo el árbol: ¿responde /hook/context?

	2026-11-20: el arnés se aterrizó y el hook 404 durante una hora porque
	`redpill-mcp.service` seguía con el código anterior. El árbol estaba verde y
	el arnés no funcionaba. Esta puerta mira al proceso, no al fichero.
	"""
	# La raíz de estado la posee core/paths.py: aquí no se compone a mano.
	from red_pill.core.paths import get_state_dir

	sock = get_state_dir() / "mcp.sock"
	if not sock.exists():
		return {"gate": "hook vivo", "ok": True, "skipped": True, "detail": "sin socket (kernel no levantado)"}
	proc = subprocess.run(
		[
			"curl",
			"-s",
			"-o",
			"/dev/null",
			"-w",
			"%{http_code}",
			"-m",
			"8",
			"--unix-socket",
			str(sock),
			"-X",
			"POST",
			"http://localhost/hook/context",
			"-H",
			"content-type: application/json",
			"-d",
			'{"harness":"premerge","session_id":"gate","need":"light","turn":1}',
		],
		capture_output=True,
		text=True,
		check=False,
	)
	code = (proc.stdout or "").strip()
	ok = code == "200"
	return {
		"gate": "hook vivo",
		"ok": ok,
		"detail": f"POST /hook/context → {code}" if ok else f"POST /hook/context → {code}: reinicia redpill-mcp.service (corre el código viejo)",
	}


def gate_budget() -> Dict[str, Any]:
	env = [sys.executable, "scripts/harness_cost.py", "--harness", "pi"]

	def boot(profile: str) -> int:
		_, out = _run(env + ["--profile", profile], timeout=600)
		m = re.search(r"\*\*arranque\*\* \| \| \*\*([0-9,]+) tok\*\*", out)
		return int(m.group(1).replace(",", "")) if m else 0

	full, gateway = boot("full"), boot("gateway")
	saving = (1 - gateway / full) if full else 0.0
	return {
		"gate": "presupuesto",
		"ok": full > 0 and saving >= GATEWAY_MIN_SAVING,
		"detail": f"arranque full {full} tok → gateway {gateway} tok ({saving:.0%} ahorro, mínimo {GATEWAY_MIN_SAVING:.0%})",
		"full": full,
		"gateway": gateway,
		"saving": round(saving, 4),
	}


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--skip-suite", action="store_true")
	ap.add_argument("--skip-bench", action="store_true")
	ap.add_argument("--sandbox", default=SANDBOX, help="contenedor donde correr capability_bench")
	ap.add_argument("--allow-no-sandbox", action="store_true", help="merge sin probar el arnés (se marca SKIP)")
	ap.add_argument("--json", default="")
	args = ap.parse_args()

	results: List[Dict[str, Any]] = [gate_style()]
	if args.skip_suite:
		results.append({"gate": "suite", "ok": True, "skipped": True, "detail": "--skip-suite"})
	else:
		results.append(gate_suite())
	if args.skip_bench:
		results.append({"gate": "capacidades", "ok": True, "skipped": True, "detail": "--skip-bench"})
	else:
		results.append(gate_capabilities(args.allow_no_sandbox, args.sandbox))
	results.append(gate_hook_vivo())
	results.append(gate_budget())

	print("\n── puerta previa al merge ──")
	for r in results:
		mark = "SKIP" if r.get("skipped") else ("PASA" if r["ok"] else "FALLA")
		print(f"  {mark:<5} {r['gate']:<12} {r['detail']}")

	bad = [r for r in results if not r["ok"]]
	special = [r for r in results if r.get("skipped")]
	if special:
		print("\n  aviso: hay puertas saltadas; el merge NO está certificado.")
	print("\n" + ("VERDE — se puede fusionar a next." if not bad else f"ROJO — no fusionar: {', '.join(r['gate'] for r in bad)}"))
	if args.json:
		Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
	return 0 if not bad else 1


if __name__ == "__main__":
	raise SystemExit(main())
