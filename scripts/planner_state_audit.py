#!/usr/bin/env python3
"""A-4 (AWAKEN-002): pre-pase determinista de estados del planner.

Sin LLM. Lee el frontmatter (`id`, `status`, `evidence`) de los documentos del
planner del desk y lo compara con la evidencia real en los repos git (ramas,
commits que **anuncian** el id en su asunto y ficheros que lo llevan, más los
commits que el propio documento declara). Lo que solo aparece en el **cuerpo**
de un commit (CHANGELOG de release, descripción de PR) se reporta como *mención*:
ni prueba trabajo ni prueba su ausencia. Emite una lista de DISCREPANCIAS
propuestas — nunca aplica cambios.

El despertar (o el operador) revisa solo lo marcado: un draft con rama/commit es
candidato a `in-progress`; un `implemented` sin merge, un `closed` sin evidencia o
un `blocked`/`paused` sin `reason` son banderas.

Uso:
uv run python scripts/planner_state_audit.py
uv run python scripts/planner_state_audit.py --repo ~/src/neon-link --json
uv run python scripts/planner_state_audit.py --only AWAKEN-002 --strict
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
	sys.path.insert(0, str(REPO_ROOT / "src"))

from red_pill.core.awakening_channel import parse_frontmatter  # noqa: E402

NEEDS_REASON = {"blocked", "paused"}
IMPLEMENTATION_STATUSES = {"in-progress", "implemented", "closed", "archived"}
NO_EVIDENCE_STATUSES = {"in-progress", "implemented", "closed"}
_ID_LIKE = re.compile(r"[A-Za-z].*[0-9]")
_GENERIC_STEMS = {"readme", "index", "design", "descripcion", "notas", "notes"}
# Prefijos de familia que no aportan identidad propia: `PLAN-CURATION-001` se
# cita en git como `CURATION-001`.
_GENERIC_PREFIXES = {"SPEC", "PLAN", "RFC", "AUDIT", "DESIGN", "DOC", "ADR", "MEM"}
# Evidencia declarada por el documento: `<repo>:<sha>` o un sha suelto. La prosa
# («R5 del 2026-10-14») no es verificable y no entra: aceptarla sería mentir al revés.
_DECLARED_SHA = re.compile(r"^(?:([A-Za-z0-9_.\-]+):)?([0-9a-f]{7,40})$")
# El `project:` del frontmatter no siempre se llama como su repo git: el kernel
# (proyecto `red-pill`) vive en el repo `sharing`, y sus evidencias se declaran
# `sharing:<sha>`. Sin este mapa, todo doc del kernel se leería como otro proyecto.
PROJECT_REPO_ALIASES = {"red-pill": "sharing"}


def _token_for(doc: Path, fm: dict) -> str:
	"""Token buscable en git. `id` del frontmatter manda; si no, el stem (o la
	carpeta padre si el stem es genérico). Tokens genéricos sin dígito → "" (no
	se busca evidencia: ensuciaría con matches irrelevantes)."""
	tid = str(fm.get("id") or "").strip()
	if tid:
		return tid
	candidate = doc.parent.name if doc.stem.lower() in _GENERIC_STEMS else doc.stem
	return candidate if _ID_LIKE.search(candidate) else ""


def _token_candidates(token: str) -> list[str]:
	"""El id exacto y sus prefijos por la derecha, del más específico al más corto.

	Un commit rara vez cita el id completo (`AWAKEN-002-DESIGN`); cita la familia
	(`AWAKEN-002`). Buscar solo el id exacto convertía trabajo real en
	`no-evidence` falsos. Solo se acepta un prefijo que aún lleve dígito: sin esa
	condición `SPEC`/`PLAN` arrastrarían medio repo y el pre-pase mentiría al revés.
	"""
	if not token:
		return []
	out = [token]
	parts = token.split("-")
	while len(parts) > 1:
		parts = parts[:-1]
		candidate = "-".join(parts)
		if not _ID_LIKE.search(candidate):
			break
		out.append(candidate)
	# Y sin el prefijo genérico: `PLAN-CURATION-001` → `CURATION-001`.
	segments = token.split("-")
	if len(segments) > 2 and segments[0].upper() in _GENERIC_PREFIXES:
		candidate = "-".join(segments[1:])
		if candidate not in out and candidate[:1].isalpha() and _ID_LIKE.search(candidate):
			out.append(candidate)
	return out


def _git(repo: Path, *args: str) -> list[str]:
	try:
		out = subprocess.run(
			["git", "-C", str(repo), *args],
			capture_output=True,
			text=True,
			timeout=30,
			check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return []
	if out.returncode != 0:
		return []
	return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def _git_root(path: Path) -> Path | None:
	lines = _git(path, "rev-parse", "--show-toplevel")
	return Path(lines[0]) if lines else None


def _live_refs(repo: Path) -> list[str]:
	"""Ramas donde aterriza el trabajo: la del remoto por defecto y las vivas.

	El flujo del kernel squash-mergea: un PR no deja commit de merge, así que
	`--merges --grep` NO ve nada y todo `closed` quedaba 'sin merge verificable'.
	Y `frankenswarm` publica en `next`, no en `main`. Se pregunta a git, no se
	adivina: primero `origin/HEAD`, luego las ramas que existan.
	"""
	out: list[str] = []
	out.extend(_git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"))
	for name in ("origin/main", "origin/next", "main", "next"):
		if name not in out and _git(repo, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"):
			out.append(name)
	return out


def _is_ancestor(repo: Path, sha: str, ref: str) -> bool:
	"""¿`sha` está contenido en `ref`? `merge-base --is-ancestor` habla por exit code."""
	try:
		out = subprocess.run(
			["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, ref],
			capture_output=True,
			text=True,
			timeout=30,
			check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return False
	return out.returncode == 0


def _landed(repos: list[Path], commits: list[str], limit: int = 5) -> list[str]:
	"""De `repo:sha subject`, los que YA están en una rama viva del repo."""
	out: list[str] = []
	for entry in commits[:limit]:
		repo_name, _, rest = entry.partition(":")
		sha = rest.split(" ", 1)[0] if rest else ""
		if not _DECLARED_SHA.match(sha or ""):
			continue
		candidates = [r for r in repos if r.name == repo_name] or list(repos)
		for repo in candidates:
			if not _has_commit(repo, sha):
				continue
			if any(_is_ancestor(repo, sha, ref) for ref in _live_refs(repo)):
				out.append(f"{repo.name}:{sha}")
				break
	return out


def _project_slug(fm: dict) -> str:
	"""Slug del `project:` del frontmatter, normalizado (`Red-Pill` → `red-pill`)."""
	raw = str(fm.get("project") or "").strip()
	return re.sub(r"[^a-z0-9_\-]+", "-", raw.casefold()) if raw else ""


def _project_repo(desk: Path, slug: str) -> Path | None:
	"""Repo git del proyecto del doc, si vive junto al desk.

	El pre-pase audita desde UN repo (el del cwd) y solo veía ese: un doc de
	`frankenswarm` salía `no-evidence` high aunque su trabajo estuviera a un
	directorio de distancia. Se busca de forma determinista —hermanos del desk y
	`<hermanos>/projects/`— y solo si el candidato es la RAÍZ de un repo git
	(si no, el toplevel es otro y se estaría mirando el repo equivocado).
	"""
	name = PROJECT_REPO_ALIASES.get(slug, slug)
	if not name:
		return None
	base = Path(desk).resolve().parent
	for candidate in (base / name, base / "projects" / name):
		if not candidate.is_dir():
			continue
		root = _git_root(candidate)
		if root and root.resolve() == candidate.resolve():
			return root.resolve()
	return None


def _covers_project(repos: list[Path], slug: str) -> bool:
	"""¿Alguno de los repos escaneados es el del proyecto declarado?

	Falso ⇒ no se ha mirado: la ausencia de evidencia NO está medida y el
	pre-pase no puede venderla como `no-evidence`.
	"""
	if not slug:
		return True
	name = PROJECT_REPO_ALIASES.get(slug, slug)
	return any(repo.name == name for repo in repos)


def _has_commit(repo: Path, sha: str) -> bool:
	"""¿Existe `sha` como commit en `repo`? `git cat-file -e` no imprime nada."""
	try:
		out = subprocess.run(
			["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
			capture_output=True,
			text=True,
			timeout=30,
			check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return False
	return out.returncode == 0


def _declared_evidence(repos: list[Path], raw: object) -> list[str]:
	"""Commits que el documento declara en `evidence:` y que existen de verdad.

	Un doc `implemented` que nombra sus commits en el frontmatter salía como
	`no-evidence` high: el pre-pase solo buscaba el id en los mensajes de git. La
	declaración **no se acepta a ciegas** — el sha tiene que existir en alguno de
	los repos escaneados. Se prefiere el repo que casa con el prefijo declarado
	(`sharing:abc123`); un worktree del mismo repo tiene otro nombre, así que si
	ninguno casa se prueba en el resto. Devuelve `repo:sha` normalizado.
	"""
	if isinstance(raw, str):
		items = [raw]
	elif isinstance(raw, (list, tuple)):
		items = [str(x) for x in raw]
	else:
		return []
	out: list[str] = []
	for item in items:
		match = _DECLARED_SHA.match(item.strip())
		if not match:
			continue
		hint, sha = match.group(1), match.group(2)
		preferred = [r for r in repos if hint and r.name == hint] if hint else []
		for repo in [*preferred, *(r for r in repos if r not in preferred)]:
			if _has_commit(repo, sha):
				entry = f"{repo.name}:{sha}"
				if entry not in out:
					out.append(entry)
				break
	return out


def _scanner_docs(planner_root: Path) -> list[Path]:
	docs: list[Path] = []
	for f in sorted(planner_root.rglob("*.md")):
		if any(part.startswith(".") for part in f.parts):
			continue
		docs.append(f)
	docs += sorted(planner_root.glob("*.md"))
	return sorted(set(docs))


def _commit_matches(repo: Path, token: str, max_commits: int, *, merges: bool = False) -> tuple[list[str], list[str]]:
	"""Commits que citan `token`: (anunciados en el asunto, solo mencionados).

	El **asunto** es el anuncio del commit: si el id está ahí, ese commit habla de
	ese trabajo. El **cuerpo** es, en la práctica, el CHANGELOG del release o la
	descripción del PR — enumera los ids de medio repo, así que un release se
	convertía en «evidencia» de cualquier documento (`draft` → `in-progress`
	falsos, tres a la vez por el mismo par de commits). El cuerpo se devuelve
	aparte como *mención*: un indicio que se enseña, no una prueba que decida.
	"""
	args = ["log", "--all", "-i", "--format=%h %s", f"--grep={token}", f"-n{max_commits}"]
	if merges:
		args.insert(2, "--merges")
	announced: list[str] = []
	mentioned: list[str] = []
	for line in _git(repo, *args):
		_, _, subject = line.partition(" ")
		(announced if token.casefold() in subject.casefold() else mentioned).append(line)
	return announced, mentioned


def _evidence(repos: list[Path], token: str, max_commits: int) -> dict:
	"""Evidencia de `token` en los repos, probando primero el id exacto.

	Devuelve `token_used`: el token con el que se encontró (el id o un prefijo
	suyo). Si `token_used != token` la evidencia es **débil** — existe, pero bajo
	la familia — y el pre-pase lo dice en vez de dar por vacío el trabajo.
	"""
	for candidate in _token_candidates(token):
		ev = _evidence_exact(repos, candidate, max_commits)
		if ev["commits"] or ev["files"] or ev["branches"] or ev["mentions"]:
			ev["token_used"] = candidate
			return ev
	return {"branches": [], "commits": [], "merges": [], "files": [], "mentions": [], "token_used": token}


def _file_pattern(token: str) -> str:
	"""Pathspec que tolera los dos separadores del id.

	`BITACORA-BIT-V2` vive en `docs/BITACORA_BIT_V2.md`: el id usa guiones y el
	fichero guiones bajos, así que `*BITACORA-BIT-V2*` no casaba y un documento
	con su fichero delante salía `no-evidence` (falso positivo medido).
	"""
	return "*" + re.sub(r"[-_]", "[-_]", token) + "*"


def _evidence_exact(repos: list[Path], token: str, max_commits: int) -> dict:
	branches: list[str] = []
	commits: list[str] = []
	merges: list[str] = []
	files: list[str] = []
	mentions: list[str] = []
	for repo in repos:
		branches += [f"{repo.name}:{b}" for b in _git(repo, "branch", "-a", "--list", f"*{token}*")]
		announced, mentioned = _commit_matches(repo, token, max_commits)
		commits += [f"{repo.name}:{c}" for c in announced]
		mentions += [f"{repo.name}:{c}" for c in mentioned]
		announced, mentioned = _commit_matches(repo, token, max_commits, merges=True)
		merges += [f"{repo.name}:{c}" for c in announced]
		mentions += [f"{repo.name}:{c}" for c in mentioned]
		files += [f"{repo.name}:{p}" for p in _git(repo, "ls-files", _file_pattern(token))]
	return {"branches": branches, "commits": commits, "merges": merges, "files": files, "mentions": list(dict.fromkeys(mentions))}


def _propose(
	status: str,
	ev: dict,
	has_reason: bool,
	has_token: bool = True,
	weak: bool = False,
	project_covered: bool = True,
	project: str = "",
) -> list[dict]:
	status = (status or "").strip().lower()
	out: list[dict] = []
	has_impl_evidence = bool(ev["commits"] or ev["files"])
	has_mention = bool(ev.get("mentions"))
	if status in NEEDS_REASON and not has_reason:
		out.append({"kind": "missing-reason", "severity": "high", "suggest": status, "reason": f"`{status}` exige `reason` en el frontmatter"})
	if not has_token:
		return out
	if status == "draft" and has_impl_evidence:
		reason = "draft sin evidencia de trabajo, pero hay rama/commit/fichero"
		if weak:
			reason += f" (bajo `{ev['token_used']}`, no el id exacto)"
		out.append(
			{
				"kind": "stale-status",
				"severity": "medium",
				"suggest": "in-progress",
				"reason": reason,
			}
		)
	if status == "ready" and has_impl_evidence:
		out.append({"kind": "stale-status", "severity": "medium", "suggest": "in-progress", "reason": "ready con trabajo ya iniciado"})
	if status == "draft" and not has_impl_evidence and has_mention:
		out.append(
			{
				"kind": "mention-only",
				"severity": "medium",
				"suggest": status,
				"reason": f"draft sin prueba de trabajo; el id solo aparece en el CUERPO de {len(ev['mentions'])} commit(s) (CHANGELOG de release / descripción de PR) — mención, no avance",
			}
		)
	if status == "in-progress" and ev["merges"]:
		out.append({"kind": "advance", "severity": "medium", "suggest": "implemented", "reason": "merge(s) que mencionan el id"})
	if status in NO_EVIDENCE_STATUSES and not has_impl_evidence and not ev["branches"]:
		if has_mention:
			out.append(
				{
					"kind": "mention-only",
					"severity": "medium",
					"suggest": status,
					"reason": f"{status} sin prueba: el id solo aparece en el CUERPO de {len(ev['mentions'])} commit(s) (CHANGELOG de release / descripción de PR) — mención, no trabajo; confirma a mano",
				}
			)
		elif project_covered:
			out.append({"kind": "no-evidence", "severity": "high", "suggest": "draft", "reason": f"{status} sin rama/commit/fichero verificable"})
		else:
			out.append(
				{
					"kind": "unscanned-project",
					"severity": "low",
					"suggest": status,
					"reason": f"proyecto `{project}` fuera de los repos escaneados: NO medido (la ausencia no está probada)",
				}
			)
	elif status in NO_EVIDENCE_STATUSES and weak:
		out.append(
			{
				"kind": "weak-evidence",
				"severity": "medium",
				"suggest": status,
				"reason": f"{status} sin evidencia del id exacto; solo bajo `{ev['token_used']}` — confirma a mano antes de degradar",
			}
		)
	if status == "closed" and not ev["merges"] and not ev.get("landed"):
		if has_mention:
			if not any(p["kind"] == "mention-only" for p in out):
				out.append(
					{
						"kind": "mention-only",
						"severity": "medium",
						"suggest": status,
						"reason": "closed sin merge ni commit de asunto verificado; solo menciones en cuerpos de commit — confirma a mano",
					}
				)
		elif project_covered:
			out.append({"kind": "unverified-closed", "severity": "high", "suggest": status, "reason": "closed sin merge verificable"})
		elif not any(p["kind"] == "unscanned-project" for p in out):
			out.append(
				{
					"kind": "unscanned-project",
					"severity": "low",
					"suggest": status,
					"reason": f"proyecto `{project}` fuera de los repos escaneados: merge no verificado por falta de repo",
				}
			)
	return out


def audit(desk: Path, repos: list[Path], only: str | None = None, max_commits: int = 40) -> list[dict]:
	planner = Path(desk) / "planner"
	if not planner.is_dir():
		return []
	results: list[dict] = []
	for doc in _scanner_docs(planner):
		try:
			fm, _ = parse_frontmatter(doc.read_text(encoding="utf-8"))
		except OSError:
			continue
		if not fm:
			continue
		status = str(fm.get("status") or "").strip()
		if not status:
			continue
		token = _token_for(doc, fm)
		if only and token.casefold() != only.casefold():
			continue
		has_reason = any(fm.get(k) for k in ("reason", "blocked_reason", "paused_reason"))
		slug = _project_slug(fm)
		# El repo del doc MANDA: los demás no hablan de su trabajo. Antes se sumaba
		# el del proyecto sin retirar el del cwd, así que un release de otro repo
		# metía sus menciones —y, si el asunto citaba el id, hasta commits— en un
		# documento ajeno (`POP-001` y `BITACORA-BIT-V2`, de `frankenswarm`, salían
		# «a revisar» por el CHANGELOG de `sharing`). Sin repo propio resoluble se
		# mantiene el barrido del cwd y la propuesta `unscanned-project` lo delata.
		own = _project_repo(desk, slug) if slug else None
		doc_repos = [own] if own else list(repos)
		covered = _covers_project(doc_repos, slug)
		ev = _evidence(doc_repos, token, max_commits) if token else {"branches": [], "commits": [], "merges": [], "files": [], "token_used": ""}
		# La evidencia DECLARADA se busca en todos los repos: el prefijo del sha es
		# una declaración humana explícita, no un barrido por id.
		all_repos = list(dict.fromkeys([*doc_repos, *repos]))
		declared = _declared_evidence(all_repos, fm.get("evidence")) if token else []
		if declared:
			ev["declared"] = declared
			ev["commits"] = [*ev["commits"], *(c for c in declared if c not in ev["commits"])]
		if ev["commits"]:
			ev["landed"] = _landed(all_repos, ev["commits"])
		weak = bool(token) and ev.get("token_used") != token and not declared
		props = _propose(status, ev, has_reason, has_token=bool(token), weak=weak, project_covered=covered, project=slug)
		if props:
			results.append(
				{
					"doc": str(doc),
					"id": token or doc.stem,
					"status": status,
					"project": slug,
					"evidence": ev,
					"proposals": props,
				}
			)
	return results


def render_markdown(results: list[dict], desk: Path, repos: list[Path]) -> str:
	lines = [
		"# Pre-pase determinista de estados del planner (AWAKEN-002 · A-4)",
		"",
		f"- Desk: `{desk}`",
		"- Repos: " + (", ".join(f"`{r}`" for r in repos) or "_(ninguno)_"),
		"",
	]
	if not results:
		lines.append("Sin discrepancias. Nada que proponer.")
		return "\n".join(lines)
	# Lo que cambia estado va primero y en detalle. Lo que solo pide confirmar una
	# mención (CHANGELOG de release) se agrupa al final: son 20 fichas de ruido si
	# se renderizan como bloques, y nadie lee 20 bloques.
	actionable = [r for r in results if any(p["kind"] != "mention-only" for p in r["proposals"])]
	mention_only = [r for r in results if all(p["kind"] == "mention-only" for p in r["proposals"])]
	for r in actionable:
		# Solo se anuncia lo que CAMBIA el estado; una propuesta que lo mantiene
		# (`weak-evidence`, `unverified-closed`) es una petición de revisión, no un destino.
		changes = [p["suggest"] for p in r["proposals"] if p["suggest"] != r["status"]]
		lines.append(f"## {r['id']} — `{r['status']}` → {', '.join(changes) if changes else 'sin cambio (revisar a mano)'}")
		lines.append(f"`{r['doc']}`")
		for p in r["proposals"]:
			lines.append(f"- **{p['kind']}** ({p['severity']}): {p['reason']} → propone `{p['suggest']}`")
		ev = r["evidence"]
		if ev.get("token_used") and ev["token_used"] != r["id"]:
			lines.append(f"  - token de evidencia: `{ev['token_used']}` (el id exacto no aparece en git)")
		if ev.get("declared"):
			lines.append("  - evidencia declarada en el frontmatter (verificada en git): " + ", ".join(f"`{x}`" for x in ev["declared"][:5]))
		if ev.get("landed"):
			lines.append("  - ya en una rama viva (sin commit de merge: el release squash-mergea): " + ", ".join(f"`{x}`" for x in ev["landed"][:5]))
		for key, label in (
			("branches", "rama(s)"),
			("commits", "commit(s)"),
			("merges", "merge(s)"),
			("files", "fichero(s)"),
			("mentions", "mención(es) en cuerpo de commit (no prueba)"),
		):
			if ev.get(key):
				lines.append(f"  - {label}: " + ", ".join(f"`{x}`" for x in ev[key][:5]))
		lines.append("")
	if mention_only:
		lines.append("## Revisar a mano — solo mención en cuerpo de commit (no prueba de trabajo)")
		lines.append("")
		for r in mention_only:
			mentions = r["evidence"].get("mentions") or []
			lines.append(f"- `{r['id']}` (`{r['status']}`) — {len(mentions)} mención(es) en CHANGELOG/PR; ni avanza ni se degrada sin confirmación")
			# Un recuento sin sha no se puede comprobar ni decidir: se citan los
			# commits que provocan la mención (y bajo qué token, si es la familia).
			family = r["evidence"].get("token_used")
			if family and family != r["id"]:
				lines.append(f"  - bajo la familia `{family}`: el id exacto no aparece en git")
			for entry in mentions[:3]:
				sha, _, subject = entry.partition(" ")
				lines.append(f"  - `{sha}` {subject}".rstrip())
			if len(mentions) > 3:
				lines.append(f"  - … y {len(mentions) - 3} más")
		lines.append("")
	lines.append("> Propuestas, no órdenes: el despertar/el operador decide. Nada se ha aplicado.")
	return "\n".join(lines)


def main() -> int:
	ap = argparse.ArgumentParser(description="Pre-pase determinista de estados del planner (AWAKEN-002 A-4).")
	ap.add_argument("--desk", default=None, help="Raíz del desk (default: AGENT_CORE_DIR).")
	ap.add_argument("--repo", action="append", default=[], help="Repo git ADICIONAL a inspeccionar (repetible); el del cwd va siempre.")
	ap.add_argument("--only", default=None, help="Solo un id concreto.")
	ap.add_argument("--max-commits", type=int, default=40)
	ap.add_argument("--json", action="store_true", help="Salida JSON.")
	ap.add_argument("--strict", action="store_true", help="Exit 1 si hay discrepancias.")
	args = ap.parse_args()

	desk = Path(args.desk) if args.desk else _default_desk()
	repos = _resolve_repos(args.repo)

	results = audit(desk, repos, only=args.only, max_commits=args.max_commits)
	if args.json:
		print(json.dumps({"desk": str(desk), "repos": [str(r) for r in repos], "results": results}, ensure_ascii=False, indent=2))
	else:
		print(render_markdown(results, desk, repos))
	return 1 if (args.strict and results) else 0


def _resolve_repos(requested: list[str]) -> list[Path]:
	"""Repos a inspeccionar: el del cwd (si es git) MÁS los declarados con `--repo`.

	`--repo` AÑADE, no reemplaza: antes, auditar desde el desk perdía la evidencia
	de los repos de proyecto (y auditar desde el kernel perdía la del desk), y los
	`implemented`/`in-progress` reales salían como `no-evidence` falsos.
	"""
	repos: list[Path] = []
	root = _git_root(Path.cwd())
	if root and root.resolve() not in repos:
		repos.append(root.resolve())
	for raw in requested:
		path = Path(raw).expanduser()
		if not path.is_dir():
			continue
		resolved = path.resolve()
		if resolved not in repos:
			repos.append(resolved)
	return repos


def _default_desk() -> Path:
	try:
		from red_pill.core.paths import get_agent_core_root

		return get_agent_core_root()
	except Exception:
		return Path.cwd()


if __name__ == "__main__":
	sys.exit(main())
