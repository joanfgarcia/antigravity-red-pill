"""Inject red-pill configuration into Pi (pi-coding-agent).

The Búnker bridge is a TS extension (`seeds/pi/extensions/red-pill.ts`). Its
per-turn RAG talks to the RedPill-Kernel MCP server (`bunker_memory_api` action
`recall`) over a persistent stdio connection using `@earendil-works/pi-mcp`; the
injector provisions that client under `<pi_dir>/node_modules` (Pi does not put
it on an extension's resolution path). Identity (wake_up_v6) and the on-demand
tools still use the red-pill CLI via `uv run`. Skills are copied into
`~/.pi/agent/skills/` (single merged dir: generic `skills/` first, then
`seeds/pi/skills/` overrides win), which Pi auto-discovers. Legacy snake_case
skill dirs (renamed to kebab-case 2026-09-10) are pruned so a reseed converges
and is idempotent.

The anchor is spliced into `<workspace>/AGENTS.override.md`: since Pi 0.87 that
file REPLACES `AGENTS.md`/`CLAUDE.md` from the same directory, so it shadows the
claude-code-project anchor (which speaks MCP) with Pi-specific text. Seeds come
from `seeds/pi/anchors/` (override) falling back to `seeds/anchors/` (generic).

Never touches `~/.pi/agent/settings.json` (provider/models belong to the
operator). The extension owns its own MCP connection; the injector never
configures `~/.pi/agent/mcp.json`.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys

logger = logging.getLogger("inject_pi")

sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "..")))
from _config_common import LEGACY_SKILL_DIRS, agent_core_vars, build_vars, env_workspace_root, subst  # noqa: E402

# `inject()` respeta `args.dry_run` (ver `_registry.inject_all`).
SUPPORTS_DRY_RUN = True


def _pi_agent_dir() -> str:
	return os.path.expanduser("~/.pi/agent")


def _workspace_root(args) -> str | None:
	"""Workspace root for the Pi anchor override: --workspace → WORKSPACE_ROOT (.env) → None."""
	return env_workspace_root(getattr(args, "workspace", None))


def _seed_anchor(repo_root: str, args, backup: bool, remove: bool = False, anchors=None) -> int:
	"""Splice red-pill anchors into <workspace>/AGENTS.override.md (Pi shadows CLAUDE.md).

	Pi >=0.87 loads AGENTS.override.md INSTEAD of AGENTS.md/CLAUDE.md from that
	directory, so this shadows the claude-code-project anchor (which speaks MCP)
	with Pi-specific text (automatic handshake, bunker_search/bunker_save).

	`anchors` = `rules_blocks` del perfil cuando hay uno: el fichero es del
	workspace (uno por caja), así que el rol vigente manda y las anclas del rol
	anterior se podan en la misma pasada.
	"""
	workspace = _workspace_root(args)
	if not workspace:
		logger.warning("· Pi anchor omitido: sin --workspace ni WORKSPACE_ROOT (.env)")
		return 0
	scripts_dir = os.path.join(repo_root, "scripts")
	if scripts_dir not in sys.path:
		sys.path.insert(0, scripts_dir)
	import inject_anchor  # noqa: E402

	variables = build_vars(argparse.Namespace(redpill_dir=repo_root, uv_path=getattr(args, "uv_path", None), workspace=workspace))
	variables.update(agent_core_vars())
	seeds_dir = os.path.join(repo_root, "seeds", "anchors")
	# Roster único (inject_anchor.BLOCK_ANCHORS) o `rules_blocks` del perfil. Sin
	# perfil, roster completo: la lista propia de pi se quedó sin `identity_pact`.
	_anchors = list(anchors) if anchors is not None else list(inject_anchor.BLOCK_ANCHORS)
	return inject_anchor.splice_ide(
		"pi",
		_anchors,
		seeds_dir,
		workspace,
		variables,
		backup=backup,
		remove=remove,
		prune=inject_anchor.KNOWN_BLOCKS if anchors is not None else (),
	)


def _managed_skill_names(repo_root: str) -> set:
	"""Skills que red-pill siembra (genéricas + override de Pi). Sólo ésas se podan."""
	names = set()
	for src in (os.path.join(repo_root, "skills"), os.path.join(repo_root, "seeds", "pi", "skills")):
		if not os.path.isdir(src):
			continue
		for entry in os.listdir(src):
			if os.path.exists(os.path.join(src, entry, "SKILL.md")):
				names.add(entry)
	return names


def _demote_unlisted_skills(dest_dir: str, keep: set, library_dir: str, repo_root: str) -> int:
	"""Mueve a la biblioteca (no anunciada) los skills sembrados que no son del rol.

	`keep` es el set de skills del bundle. El resto de directorios se deja intacto:
	un skill propio del Operador no está en los seeds y no se toca. Mover, no borrar:
	sigue consultable y el cambio de rol es reversible.
	"""
	if not os.path.isdir(dest_dir):
		return 0
	managed = _managed_skill_names(repo_root)
	moved = 0
	for entry in sorted(os.listdir(dest_dir)):
		if entry in keep or entry not in managed:
			continue
		src = os.path.join(dest_dir, entry)
		if not os.path.isdir(src):
			continue
		os.makedirs(library_dir, exist_ok=True)
		dst = os.path.join(library_dir, entry)
		if os.path.exists(dst):
			shutil.rmtree(src)
		else:
			shutil.move(src, dst)
		moved += 1
		logger.info(f"  skill '{entry}' → biblioteca (fuera del rol)")
	return moved


def _read_seed(path: str) -> str:
	with open(path, encoding="utf-8") as f:
		return f.read()


def _overridden_files(override_dir: str) -> set:
	"""Set of (skill, relpath) covered by an IDE-specific override dir.

	Used to SKIP those files in the generic pass: if the generic copy ran first
	and the override after, the next generic pass would see a diff and rewrite
	the override's file, so the reseed would never converge."""
	out: set = set()
	if not os.path.isdir(override_dir):
		return out
	for skill in os.listdir(override_dir):
		skill_dir = os.path.join(override_dir, skill)
		if not os.path.isdir(skill_dir):
			continue
		for root, _dirs, files in os.walk(skill_dir):
			for name in files:
				out.add((skill, os.path.relpath(os.path.join(root, name), skill_dir)))
	return out


def _pi_skill_capability(skill_md: str) -> str | None:
	"""Lee `capability:` del frontmatter YAML de un SKILL.md (sin dependencias)."""
	try:
		with open(skill_md, encoding="utf-8") as f:
			lines = f.read().splitlines()
	except OSError:
		return None
	if not lines or lines[0].strip() != "---":
		return None
	for line in lines[1:]:
		if line.strip() == "---":
			break
		if line.startswith("capability:"):
			return line.split(":", 1)[1].strip() or None
	return None


def _skill_frontmatter_error(skill_md: str) -> str | None:
	"""Valida que el frontmatter YAML de un SKILL.md parsea. Devuelve el error o None.

	Un frontmatter inválido (p.ej. `description:` con `: ` sin comillas) hace que Pi
	lo reporte como *Skill conflict* al arrancar. Mejor abortar el deploy de ese skill
	con un error claro que propagar la bomba al `~/.pi` del operador en cada reseed.
	"""
	try:
		with open(skill_md, encoding="utf-8") as f:
			txt = f.read()
	except OSError as e:  # noqa: PERF203
		return f"no se pudo leer: {e}"
	if not txt.startswith("---"):
		return None  # sin frontmatter no hay nada que validar
	parts = txt.split("---", 2)
	if len(parts) < 3:
		return "frontmatter '---' sin cerrar"
	try:
		import yaml

		meta = yaml.safe_load(parts[1])
	except Exception as e:  # noqa: BLE001
		return str(e).splitlines()[0]
	if not isinstance(meta, dict):
		return "el frontmatter no es un mapping YAML"
	if not meta.get("name"):
		return "falta 'name' en el frontmatter"
	return None


def _deploy_skills(src_dir: str, dest_dir: str, variables: dict, backup: bool, skip: set | None = None, only: set | None = None) -> int:
	"""Copy a skills dir into the Pi skills root. Returns number of changed skills."""
	changed = 0
	if not os.path.isdir(src_dir):
		return 0
	os.makedirs(dest_dir, exist_ok=True)
	for skill_entry in sorted(os.listdir(src_dir)):
		if only is not None and skill_entry not in only:
			continue
		skill_src = os.path.join(src_dir, skill_entry)
		skill_md = os.path.join(skill_src, "SKILL.md")
		if not os.path.isdir(skill_src) or not os.path.exists(skill_md):
			continue
		_fm_err = _skill_frontmatter_error(skill_md)
		if _fm_err is not None:
			logger.error(f"✗ Pi skill '{skill_entry}': frontmatter inválido ({_fm_err}) → NO desplegado")
			continue
		_cap = _pi_skill_capability(skill_md)
		if _cap is not None:
			try:
				from red_pill.core.capabilities import enabled_for

				_keep = enabled_for(_cap)
			except Exception as e:  # noqa: BLE001
				logger.warning(f"  Skill '{skill_entry}': gate no disponible ({e}) → skip (capability='{_cap}')")
				_keep = False
			if not _keep:
				logger.info(f"  Skill '{skill_entry}' gated (capability '{_cap}' inactiva) → skip")
				continue
		skill_dest_dir = os.path.join(dest_dir, skill_entry)
		os.makedirs(skill_dest_dir, exist_ok=True)
		skill_changed = 0
		for root, dirs, files in os.walk(skill_src):
			dirs[:] = [d for d in dirs if d != "__pycache__"]
			rel_root = os.path.relpath(root, skill_src)
			dest_root = skill_dest_dir if rel_root == "." else os.path.join(skill_dest_dir, rel_root)
			os.makedirs(dest_root, exist_ok=True)
			for name in files:
				src_file = os.path.join(root, name)
				if skip and (skill_entry, os.path.relpath(src_file, skill_src)) in skip:
					continue  # lo pisa un override específico-IDE
				dest_file = os.path.join(dest_root, name)
				if name.endswith(".md"):
					resolved = subst(_read_seed(src_file), variables)
					if os.path.exists(dest_file):
						with open(dest_file, encoding="utf-8") as f:
							if f.read() == resolved:
								continue
						if backup:
							shutil.copy2(dest_file, dest_file + ".bak")
					with open(dest_file, "w", encoding="utf-8") as f:
						f.write(resolved)
				else:
					if os.path.exists(dest_file):
						with open(dest_file, "rb") as a, open(src_file, "rb") as b:
							if a.read() == b.read():
								continue
						if backup:
							shutil.copy2(dest_file, dest_file + ".bak")
					shutil.copy2(src_file, dest_file)
				skill_changed += 1
		if skill_changed:
			changed += 1
			logger.info(f"✓ Pi skill '{skill_entry}' deployed → {skill_dest_dir}")
		else:
			logger.info(f"· Pi skill '{skill_entry}' sin cambios")
	return changed


def _prune_legacy(skills_dest: str) -> int:
	"""Remove pre-rename snake_case skill dirs. Returns number removed."""
	removed = 0
	for legacy in LEGACY_SKILL_DIRS:
		path = os.path.join(skills_dest, legacy)
		if os.path.isdir(path):
			shutil.rmtree(path)
			logger.info(f"✓ Pi legacy skill '{legacy}' removed")
			removed += 1
	return removed


def _deploy_extension(pi_dir: str, seed: str, variables: dict, backup: bool) -> int:
	extensions_dir = os.path.join(pi_dir, "extensions")
	os.makedirs(extensions_dir, exist_ok=True)
	# El nombre SALE del seed: con "red-pill.ts" fijo, desplegar la segunda extensión
	# (`red-pill-context.ts`) pisaba la primera y el relay desaparecía sin avisar.
	dest = os.path.join(extensions_dir, os.path.basename(seed))
	resolved = subst(_read_seed(seed), variables)
	if os.path.exists(dest):
		with open(dest, encoding="utf-8") as f:
			if f.read() == resolved:
				logger.info(f"· Pi extension '{os.path.basename(seed)}' sin cambios")
				return 0
		if backup:
			shutil.copy2(dest, dest + ".bak")
	with open(dest, "w", encoding="utf-8") as f:
		f.write(resolved)
	logger.info(f"✓ Pi extension deployed → {dest}")
	return 1


# `@earendil-works/pi-mcp` is the standalone MCP client published with Pi. It is
# not on an extension's module resolution path, so we provision it into the
# agent dir. Pinned to Pi's own version for wire-protocol compatibility.
PI_MCP_PACKAGE = "@earendil-works/pi-mcp"
PI_MCP_FALLBACK_VERSION = "1.0.2"


def _pi_mcp_version() -> str:
	"""Target pi-mcp version = the running Pi version (best effort)."""
	import re
	import subprocess

	for cmd in (["pi", "--version"], ["pi", "-v"]):
		try:
			out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
			match = re.match(r"(\d+\.\d+\.\d+)", (out.stdout or "").strip())
			if match:
				return match.group(1)
		except Exception:
			continue
	return PI_MCP_FALLBACK_VERSION


def _ensure_pi_mcp_client(pi_dir: str) -> int:
	"""Provision @earendil-works/pi-mcp into <pi_dir>/node_modules so the
	extension can `import { McpClient }`. Best-effort and idempotent: skips when
	it already exists or when npm is unavailable (logs a warning). Returns the
	number of changes."""
	import subprocess

	pkg_dir = os.path.join(pi_dir, "node_modules", "@earendil-works", "pi-mcp")
	if os.path.isdir(pkg_dir):
		logger.info("· pi-mcp client ya provisionado")
		return 0
	npm = shutil.which("npm")
	if not npm:
		logger.warning(f"⚠ npm no encontrado: la extensión Pi necesita {PI_MCP_PACKAGE}. Instálalo a mano en {pi_dir}")
		return 0
	spec = f"{PI_MCP_PACKAGE}@{_pi_mcp_version()}"
	try:
		result = subprocess.run([npm, "install", "--prefix", pi_dir, "--no-save", spec], capture_output=True, text=True, timeout=300)
	except Exception as exc:
		logger.warning(f"⚠ No se pudo provisionar {spec}: {exc}")
		return 0
	if result.returncode != 0:
		logger.warning(f"⚠ npm install {spec} falló: {(result.stderr or '').strip()[:200]}")
		return 0
	logger.info(f"✓ pi-mcp client provisionado → {pkg_dir} ({spec})")
	return 1


def _remove(pi_dir: str, repo_root: str, args) -> int:
	removed = 0
	for ext_name in ("red-pill.ts", "red-pill-context.ts"):
		ext = os.path.join(pi_dir, "extensions", ext_name)
		if os.path.exists(ext):
			os.remove(ext)
			removed += 1
			logger.info(f"✓ Pi extension '{ext_name}' removed")
	skills_dest = os.path.join(pi_dir, "skills")
	managed = list(LEGACY_SKILL_DIRS)
	for src in (os.path.join(repo_root, "skills"), os.path.join(repo_root, "seeds", "pi", "skills")):
		if os.path.isdir(src):
			for entry in os.listdir(src):
				if os.path.exists(os.path.join(src, entry, "SKILL.md")):
					managed.append(entry)
	for name in sorted(set(managed)):
		path = os.path.join(skills_dest, name)
		if os.path.isdir(path):
			shutil.rmtree(path)
			removed += 1
			logger.info(f"✓ Pi skill '{name}' removed")
	removed += _seed_anchor(repo_root, args, backup=False, remove=True)
	return removed


def inject(args: argparse.Namespace) -> int:
	pi_dir = _pi_agent_dir()
	if not os.path.isdir(pi_dir):
		os.makedirs(pi_dir, exist_ok=True)

	script_dir = os.path.dirname(os.path.abspath(__file__))
	# scripts/inject/pi/ → scripts/ → repo root
	repo_root = os.path.normpath(os.path.join(script_dir, "..", "..", ".."))
	if not getattr(args, "redpill_dir", None):
		args.redpill_dir = repo_root  # RED_PILL_DIR / RED_PILL_CMD necesitan el checkout

	variables = build_vars(args)
	backup = not getattr(args, "no_backup", False)

	# ── Perfil (RFC-HARNESS-001 P3b/P4): rol × capacidad × egress ─────────────
	bundle = None
	profile = str(getattr(args, "profile", "full") or "full")
	if profile != "full":
		parts = profile.split(":")
		if len(parts) != 3:
			logger.error("--profile debe ser `rol:capacidad:egress` (p.ej. worker:local-9b:none) o `full`")
			return 2
		sys.path.insert(0, os.path.join(repo_root, "src"))
		from red_pill.harness.profile import ProfileError, describe, resolve

		try:
			bundle = resolve(parts[0], parts[1], parts[2])
		except ProfileError as exc:
			logger.error(f"--profile inválido: {exc}")
			return 2
		print(describe(bundle))

	if getattr(args, "dry_run", False):
		logger.info("— dry-run: no se escribe nada —")
		if bundle is not None:
			logger.info(f"skills a instalar: {bundle.skills}")
			logger.info(f"biblioteca: {bundle.skills_library or '—'}")
		logger.info(f"extensiones: red-pill.ts + red-pill-context.ts → {pi_dir}/extensions")
		return 0

	if getattr(args, "remove", False):
		return _remove(pi_dir, repo_root, args)

	changed = 0
	# 1. Extensiones: captura/relay (`red-pill.ts`) e identidad por hook
	#    (`red-pill-context.ts`, P4). Las dos, siempre: sin la segunda no hay identidad.
	for ext_name in ("red-pill.ts", "red-pill-context.ts"):
		seed_ext = os.path.join(repo_root, "seeds", "pi", "extensions", ext_name)
		if os.path.exists(seed_ext):
			changed += _deploy_extension(pi_dir, seed_ext, variables, backup)
	changed += _ensure_pi_mcp_client(pi_dir)

	# 2. Skills: genérico primero, override específico-IDE después (gana).
	#    Los ficheros pisados por el override se SALTAN en la pasada genérica
	#    (si no, la genérica los re-copia y el reseed no converge).
	skills_dest = os.path.join(pi_dir, "skills")
	pi_skills_src = os.path.join(repo_root, "seeds", "pi", "skills")
	# `all_skills` (rol `none`) = no podar: la instalación estándar anuncia todo.
	only = None if (bundle is None or bundle.all_skills) else set(bundle.skills)
	changed += _deploy_skills(os.path.join(repo_root, "skills"), skills_dest, variables, backup, skip=_overridden_files(pi_skills_src), only=only)
	changed += _deploy_skills(pi_skills_src, skills_dest, variables, backup, only=only)
	# Volver de `standard` a un rol acotado tiene que retirar del anuncio las
	# skills que sobran. Sólo en cajas (`--exclusive-skills`), y sólo skills que
	# red-pill sembró: un skill propio del Operador no se toca nunca.
	if only is not None and getattr(args, "exclusive_skills", False):
		library_dest = os.path.join(pi_dir, "library", "skills")
		changed += _demote_unlisted_skills(skills_dest, only, library_dest, repo_root)
	if bundle is not None and bundle.skills_library:
		# Biblioteca: NO la descubre Pi (no se anuncia), pero está en disco y la
		# boot card dice dónde. Así el presupuesto no se paga y nada desaparece.
		library_dest = os.path.join(pi_dir, "library", "skills")
		only_lib = set(bundle.skills_library)
		changed += _deploy_skills(os.path.join(repo_root, "skills"), library_dest, variables, backup, only=only_lib)
		changed += _deploy_skills(pi_skills_src, library_dest, variables, backup, only=only_lib)
	# 3. Prune legados snake_case → reseed convergente e idempotente.
	changed += _prune_legacy(skills_dest)

	# 4. Anchor → <workspace>/AGENTS.override.md (shadows CLAUDE.md for Pi, which
	#    carries the claude-code MCP anchor). Pi-specific seed overrides win.
	# Rol sin `rules_blocks` (`none`) = roster completo; sin perfil, también.
	# `identity_mode=minimal` manda sobre el rol: un 4B sólo adopta la tarjeta.
	sys.path.insert(0, os.path.join(repo_root, "scripts"))
	import inject_anchor  # noqa: PLC0415

	if bundle is None:
		role_blocks = list(inject_anchor.BLOCK_ANCHORS)
	elif bundle.identity_mode == "minimal":
		role_blocks = ["minimal"]
	else:
		role_blocks = list(bundle.rules_blocks) or list(inject_anchor.BLOCK_ANCHORS)
	# El bundle escrito describe lo que se sembró, no sólo lo que el rol declaró:
	# en un 4B `identity_mode=minimal` sustituye las reglas del rol por `minimal`.
	if bundle is not None:
		import json as _json

		_seeded = bundle.to_dict()
		_seeded["rules_blocks"] = list(role_blocks)
		(open(os.path.join(pi_dir, "bundle.json"), "w", encoding="utf-8")).write(_json.dumps(_seeded, ensure_ascii=False, indent=1))
		logger.info(f"✓ bundle del perfil escrito en {os.path.join(pi_dir, 'bundle.json')}")
	changed += _seed_anchor(repo_root, args, backup, remove=False, anchors=role_blocks)

	return changed


def main() -> int:
	"""CLI mínima para sembrar Pi desde dentro de una caja (p. ej. Dokimé/Titanium).

	El adaptador no tenía entrada propia: `inject_cli.py` lo llamaba en el host. El
	banco vive dentro del contenedor y necesita el mismo camino para skills, anclas
	y `bundle.json` sin depender del `~/.pi` del Operador.
	"""
	import argparse

	repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
	ap = argparse.ArgumentParser(description="Siembra Pi (skills, anclas y bundle) en un workspace.")
	ap.add_argument("--workspace", required=True)
	ap.add_argument("--profile", default="full", help="`rol:capacidad:egress` o `full`")
	ap.add_argument("--redpill-dir", default=repo_root)
	ap.add_argument("--no-backup", action="store_true")
	ap.add_argument("--update", action="store_true", help="reescribe aunque no haya cambios")
	ap.add_argument(
		"--exclusive-skills",
		action="store_true",
		help="mueve a la biblioteca los skills sembrados que no son del rol (sólo cajas; nunca toca skills del Operador)",
	)
	ap.add_argument("--remove", action="store_true", help="retira red-pill de Pi")
	args = ap.parse_args()
	inject(args)
	return 0


if __name__ == "__main__":
	sys.exit(main())
