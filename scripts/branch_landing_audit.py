#!/usr/bin/env python3
"""Auditoría determinista de ramas pendientes de aterrizar.

El handoff del despertar dice cosas como «rama X pendiente de aterrizar». Esa
frase se ha demostrado falsa varias veces en las dos direcciones:

- ramas dadas por pendientes cuyo contenido **ya está** en `main` (el release
  squash-mergea: los SHA cambian, el contenido no), y
- ramas realmente pendientes que nadie miraba porque el log anterior decía que
  ya habían entrado.

`git branch --merged` no sirve con squash y `git cherry` tampoco (su patch-id es
por commit: un squash de N commits no coincide con ninguno de los N). Este script
mide lo único que no engaña: **el contenido**. Para cada rama compara los ficheros
que tocó con la versión que tiene el destino; si son idénticos, no hay nada que
aterrizar, diga lo que diga el log.

Estados por rama:

- `merged`       — el tip es ancestro del destino (merge real).
- `no_changes`   — la rama no cambia ningún fichero respecto a su base.
- `same_content` — tocó ficheros, pero el destino ya tiene ese contenido
                   (squash/cherry-pick/recreación): nada que aterrizar.
- `clean`        — hay contenido distinto y el merge es limpio: pendiente real.
- `conflict`     — hay contenido distinto y el merge conflictúa.
- `unrelated`    — sin base común con el destino.

`same_content` se decide por tres vías, de la más fuerte a la más débil, y el
campo `evidence` dice cuál se usó:

- `merge_noop`        — mergear la rama en el destino no cambiaría el árbol.
- `whole_file`        — los ficheros que tocó son idénticos en el destino.
- `additions_present` — sus adiciones (sin borrados) ya están, literales, en el
                        destino. Cubre el caso que rompía la comparación por
                        fichero: una rama squash-mergeada cuyo fichero siguió
                        creciendo después (CHANGELOG, índices), que si no se
                        quedaba marcada como pendiente para siempre.

Las ramas `parked/*` se auditan (visibilidad) pero **no cuentan** para
`--strict`: una rama aparcada con `reason` es pendiente por diseño y no debe
tener el gate en rojo permanente. Con `--include-parked` sí cuentan.

Uso:
uv run python scripts/branch_landing_audit.py
uv run python scripts/branch_landing_audit.py --target next --json
uv run python scripts/branch_landing_audit.py --repo ~/src/neon-link --pattern 'awaken/*'
uv run python scripts/branch_landing_audit.py --strict --include-parked
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATTERNS = ("awaken/*", "parked/*")
PENDING_STATUSES = {"clean", "conflict"}
PARKED_PREFIX = "parked/"
STATUS_ORDER = {"merged": 0, "no_changes": 1, "same_content": 2, "clean": 3, "unrelated": 4, "conflict": 5}


@dataclass
class Verdict:
	branch: str
	tip: str
	base: str
	ahead: int
	status: str
	files_touched: int = 0
	files_differing: list[str] = field(default_factory=list)
	conflict_files: list[str] = field(default_factory=list)
	evidence: str = ""

	def as_dict(self) -> dict:
		return {
			"branch": self.branch,
			"tip": self.tip,
			"base": self.base,
			"ahead": self.ahead,
			"status": self.status,
			"evidence": self.evidence,
			"files_touched": self.files_touched,
			"files_differing": self.files_differing,
			"conflict_files": self.conflict_files,
		}


def is_parked(verdict: Verdict) -> bool:
	return verdict.branch.startswith(PARKED_PREFIX)


def is_pending(verdict: Verdict, include_parked: bool = False) -> bool:
	"""Pendiente de aterrizar de verdad: `parked/*` solo cuenta si se pide."""
	if verdict.status not in PENDING_STATUSES:
		return False
	return include_parked or not is_parked(verdict)


class GitError(RuntimeError):
	pass


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
	proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
	if check and proc.returncode != 0:
		raise GitError(f"git {' '.join(args)} → {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}")
	return proc


def _rev(repo: Path, ref: str) -> str | None:
	proc = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
	return proc.stdout.strip() or None


def _short(repo: Path, sha: str) -> str:
	return _git(repo, "rev-parse", "--short", sha).stdout.strip()


def _is_ancestor(repo: Path, ref: str, target: str) -> bool:
	return _git(repo, "merge-base", "--is-ancestor", ref, target, check=False).returncode == 0


def _branches(repo: Path, patterns: tuple[str, ...]) -> list[str]:
	proc = _git(repo, "for-each-ref", "--format=%(refname:short)", "--", *(f"refs/heads/{p}" for p in patterns))
	return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _merge_tree(repo: Path, target: str, branch: str) -> tuple[str | None, list[str]]:
	"""Árbol resultante de mergear `branch` en `target`, y ficheros en conflicto.

	`(árbol, [])` si el merge es limpio; `(árbol, ficheros)` si conflictúa. El
	árbol sirve para lo que no engaña: si coincide con el del destino, mergear la
	rama no cambiaría nada (nada que aterrizar).
	"""
	proc = _git(repo, "merge-tree", "--write-tree", "--name-only", target, branch, check=False)
	if proc.returncode == 0:
		return proc.stdout.splitlines()[0].strip() or None, []
	if proc.returncode != 1:
		raise GitError(f"git merge-tree {target} {branch} → {proc.returncode}: {proc.stderr.strip()}")
	# Salida: árbol + nombres en conflicto, línea en blanco, mensajes informativos.
	head = [line.strip() for line in proc.stdout.split("\n\n")[0].splitlines() if line.strip()]
	tree = head[0] if head else None
	names = [line for line in head[1:] if line]
	return tree, (names or ["(conflicto sin nombre de fichero)"])


def _added_blocks(patch: str) -> list[list[str]]:
	"""Bloques contiguos de líneas añadidas en un diff (`-U0`)."""
	blocks: list[list[str]] = []
	current: list[str] = []
	for line in patch.splitlines():
		if line.startswith("@@"):
			if current:
				blocks.append(current)
			current = []
		elif line.startswith("+") and not line.startswith("+++"):
			current.append(line[1:])
		elif current:
			blocks.append(current)
			current = []
	if current:
		blocks.append(current)
	return blocks


def _contains_block(lines: list[str], block: list[str]) -> bool:
	if not block:
		return False
	width = len(block)
	return any(lines[i : i + width] == block for i in range(len(lines) - width + 1))


def _additions_present(repo: Path, base: str, target: str, branch: str, path: str) -> bool:
	"""¿Están en el destino las líneas que la rama AÑADE a `path`?

	Solo se pronuncia en el caso seguro: diff **solo de adiciones** (sin borrados,
	sin binario, sin cambio de modo). Si la rama borra o reescribe, la respuesta es
	"no lo sé" y se devuelve False: mejor marcar pendiente de más que dar por
	aterrizado lo que no está.
	"""
	numstat = _git(repo, "diff", "--numstat", f"{base}..{branch}", "--", path, check=False).stdout.strip()
	if not numstat:
		return False
	fields = numstat.split("\t")
	if len(fields) < 2:
		return False
	added, removed = fields[0], fields[1]
	if added == "-" or added == "0" or removed != "0":
		return False
	blocks = _added_blocks(_git(repo, "diff", "--no-color", "-U0", f"{base}..{branch}", "--", path).stdout)
	if not blocks:
		return False
	show = _git(repo, "show", f"{target}:{path}", check=False)
	if show.returncode != 0:
		return False
	lines = show.stdout.splitlines()
	return all(_contains_block(lines, block) for block in blocks)


def audit_branch(repo: Path, branch: str, target: str) -> Verdict:
	tip_sha = _rev(repo, branch)
	if not tip_sha:
		raise GitError(f"rama inexistente: {branch}")
	tip = _short(repo, tip_sha)
	if _is_ancestor(repo, branch, target):
		return Verdict(branch=branch, tip=tip, base=tip, ahead=0, status="merged")

	mb_proc = _git(repo, "merge-base", target, branch, check=False)
	base_sha = mb_proc.stdout.strip() if mb_proc.returncode == 0 else ""
	if not base_sha:
		return Verdict(branch=branch, tip=tip, base="-", ahead=0, status="unrelated")
	base = _short(repo, base_sha)
	ahead = int(_git(repo, "rev-list", "--count", f"{target}..{branch}").stdout.strip() or 0)

	touched = [p for p in _git(repo, "diff", "--name-only", f"{base_sha}..{branch}").stdout.splitlines() if p.strip()]
	if not touched:
		return Verdict(branch=branch, tip=tip, base=base, ahead=ahead, status="no_changes")

	target_tree = _git(repo, "rev-parse", f"{target}^{{tree}}").stdout.strip()
	merged_tree, conflicts = _merge_tree(repo, target, branch)
	if merged_tree and merged_tree == target_tree:
		return Verdict(
			branch=branch,
			tip=tip,
			base=base,
			ahead=ahead,
			status="same_content",
			files_touched=len(touched),
			evidence="merge_noop",
		)

	differing = [p for p in _git(repo, "diff", "--name-only", target, branch, "--", *touched).stdout.splitlines() if p.strip()]
	if not differing:
		return Verdict(
			branch=branch,
			tip=tip,
			base=base,
			ahead=ahead,
			status="same_content",
			files_touched=len(touched),
			evidence="whole_file",
		)

	# El fichero pudo seguir creciendo después del squash: si sus adiciones ya
	# están literales en el destino, no hay nada que aterrizar aunque el diff
	# completo difiera (y aunque el merge conflicte por el texto vecino).
	if all(_additions_present(repo, base_sha, target, branch, p) for p in differing):
		return Verdict(
			branch=branch,
			tip=tip,
			base=base,
			ahead=ahead,
			status="same_content",
			files_touched=len(touched),
			files_differing=differing,
			evidence="additions_present",
		)

	status = "conflict" if conflicts else "clean"
	return Verdict(
		branch=branch,
		tip=tip,
		base=base,
		ahead=ahead,
		status=status,
		files_touched=len(touched),
		files_differing=differing,
		conflict_files=conflicts or [],
	)


def audit(repo: Path, target: str, patterns: tuple[str, ...]) -> list[Verdict]:
	if not _rev(repo, target):
		raise GitError(f"destino inexistente en {repo}: {target}")
	verdicts = [audit_branch(repo, b, target) for b in _branches(repo, patterns) if b != target]
	verdicts.sort(key=lambda v: (STATUS_ORDER.get(v.status, 9), v.branch))
	return verdicts


def _git_root(path: Path) -> Path | None:
	proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
	return Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None


def render(verdicts: list[Verdict], repo: Path, target: str, include_parked: bool = False) -> str:
	lines = [
		"# Auditoría de ramas pendientes de aterrizar",
		"",
		f"- Repo: `{repo}`",
		f"- Destino: `{target}`",
		"",
	]
	if not verdicts:
		lines.append("Sin ramas que auditar.")
		return "\n".join(lines)
	lines.append("| rama | tip | base | ahead | estado | ficheros |")
	lines.append("|---|---|---|---|---|---|")
	for v in verdicts:
		files = "—" if not v.files_touched else f"{len(v.files_differing)}/{v.files_touched} distintos"
		status = f"**{v.status}**" + (f" · {v.evidence}" if v.evidence else "")
		lines.append(f"| `{v.branch}` | `{v.tip}` | `{v.base}` | {v.ahead} | {status} | {files} |")
	lines.append("")
	pending = [v for v in verdicts if is_pending(v, include_parked)]
	held = [v for v in verdicts if v.status in PENDING_STATUSES and not is_pending(v, include_parked)]
	landed = [v for v in verdicts if v.status == "same_content"]
	if landed:
		lines.append(
			"> `same_content`: el destino ya tiene ese contenido (squash/cherry-pick). "
			"La rama se puede borrar; no hay nada que aterrizar aunque el log diga lo contrario."
		)
	if held:
		lines.append("")
		lines.append(
			f"> {len(held)} rama(s) `parked/*` con contenido pendiente **por diseño**: "
			"no cuentan para `--strict` (usa `--include-parked` para contarlas)."
		)
	if pending:
		lines.append("")
		lines.append(f"## Pendientes de aterrizar ({len(pending)})")
		for v in pending:
			lines.append(f"- `{v.branch}` — {v.status}, {v.ahead} commit(s) sobre `{v.base}`")
			for f in v.files_differing[:10]:
				lines.append(f"  - `{f}`")
			for f in v.conflict_files[:10]:
				lines.append(f"  - conflicto: `{f}`")
	else:
		lines.append("")
		lines.append("Ninguna rama con contenido pendiente.")
	return "\n".join(lines)


def main() -> int:
	ap = argparse.ArgumentParser(description="Auditoría determinista de ramas pendientes de aterrizar (contenido, no SHA).")
	ap.add_argument("--repo", action="append", default=[], help="Repo git a auditar (repetible; ADICIONAL — el del cwd va siempre).")
	ap.add_argument("--target", default="main", help="Rama destino (default: main).")
	ap.add_argument("--pattern", action="append", default=[], help=f"Patrón de rama (repetible; default: {', '.join(DEFAULT_PATTERNS)}).")
	ap.add_argument("--json", action="store_true", help="Salida JSON.")
	ap.add_argument(
		"--strict",
		action="store_true",
		help="Exit 1 si alguna rama tiene contenido pendiente (clean/conflict); `parked/*` no cuenta salvo --include-parked.",
	)
	ap.add_argument(
		"--include-parked",
		action="store_true",
		help="Cuenta también las ramas `parked/*` como pendientes (para --strict). Se auditan siempre.",
	)
	args = ap.parse_args()

	patterns = tuple(args.pattern) or DEFAULT_PATTERNS
	repos: list[Path] = []
	root = _git_root(Path.cwd())
	if root:
		repos.append(root.resolve())
	for raw in args.repo:
		path = Path(raw).expanduser().resolve()
		found = _git_root(path)
		if not found:
			print(f"aviso: {path} no es un repo git; se ignora", file=sys.stderr)
			continue
		if found.resolve() not in repos:
			repos.append(found.resolve())
	if not repos:
		print("error: ni el cwd ni --repo apuntan a un repo git", file=sys.stderr)
		return 2

	payload: dict[str, object] = {"target": args.target, "repos": []}
	pending = 0
	for repo in repos:
		try:
			verdicts = audit(repo, args.target, patterns)
		except GitError as exc:
			print(f"error: {repo}: {exc}", file=sys.stderr)
			return 2
		pending += sum(1 for v in verdicts if is_pending(v, args.include_parked))
		payload["repos"].append({"repo": str(repo), "verdicts": [v.as_dict() for v in verdicts]})  # type: ignore[index]
		if not args.json:
			print(render(verdicts, repo, args.target, args.include_parked))
			print()
	if args.json:
		print(json.dumps(payload, ensure_ascii=False, indent=2))
	return 1 if (args.strict and pending) else 0


if __name__ == "__main__":
	sys.exit(main())
