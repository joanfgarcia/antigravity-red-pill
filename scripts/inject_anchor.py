"""Inject/merge red-pill anchor blocks into IDE instruction files.

Sibling of ``inject_mcp.py``. Where inject_mcp merges MCP server entries into
``*.json`` configs by key, this merges Markdown anchor *blocks* (the Sovereign
Handshake, the Agent_Core directive) into IDE instruction files (GEMINI.md,
CLAUDE.md, …) by a delimited, versioned region.

Guiding principle: red-pill is a GUEST, never the owner. Every write preserves
all foreign content; we only ever create/replace/remove OUR own marked region:

<!-- REDPILL:BEGIN <anchor> v=N -->
…seed body (placeholders resolved)…
<!-- REDPILL:END <anchor> -->

Seeds live in ``seeds/anchors/<anchor>.md`` and are passed through the shared
``subst()`` so placeholders like ${WORKSPACE_ROOT}/${AGENT_CORE_DIR} resolve.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("anchor_injector")

# Shared placeholder helpers live alongside this script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _config_common import agent_core_vars, build_vars, subst  # noqa: E402

# ── Anchor block version (bump to force a re-splice on upgrade) ───────────────
# Canonical order + roster: the SINGLE source every deployer imports. `inject_opencode`
# used to hardcode a different subset (missing `identity_pact`, adding `frontmatter_docs`
# only there), so each target drifted to a different rule set.
# `minimal` NO entra en el roster: es un bloque opt-in para perfiles pequeños
# (p. ej. Dokimé) que arrancan sólo con identidad. Añadirlo aquí lo sembraría en
# todos los arneses y duplicaría la identidad que ya inyecta el hook.
BLOCK_ANCHORS = (
	"sovereign_handshake",
	"agent_core",
	"knowledge_access",
	"frontmatter_docs",
	"job_dag_execution",
	"identity_pact",
)

BLOCK_VERSION = {
	"sovereign_handshake": 6,
	"agent_core": 2,
	"knowledge_access": 6,
	"frontmatter_docs": 4,
	"job_dag_execution": 3,
	"identity_pact": 2,
}


# Anclas que red-pill sembró y ya no siembra. Sin esta lista su bloque marcado se
# quedaba para siempre en el fichero del IDE (el `git_workflow` de opencode seguía
# en AGENTS.md meses después de salir del roster). Sólo se poda lo que está aquí:
# un bloque REDPILL desconocido puede ser de otro sembrador (p. ej. `desk`), y ese
# se avisa en la auditoría, no se borra.
RETIRED_ANCHORS = frozenset({"git_workflow"})

# Anclas que red-pill conoce y puede podar. Fuera de este conjunto no se toca nada
# (un bloque desconocido puede ser de otro sembrador, p. ej. el desk).
KNOWN_BLOCKS = frozenset(BLOCK_ANCHORS) | RETIRED_ANCHORS | frozenset({"minimal"})

_ANY_BEGIN_RE = re.compile(r"<!-- REDPILL:BEGIN (\S+)(?: v=\d+)? -->")


def resolve_profile(profile):
	"""Resuelve `rol:capacidad:egress` → Bundle. `full` (o vacío) → None.

	Vive aquí, y no en cada inyector, para que el contrato de `--profile` sea uno:
	Pi y opencode leerán el mismo bundle y el rol no dependerá de por dónde entró
	la siembra.
	"""
	spec = str(profile or "").strip()
	if not spec or spec == "full":
		return None
	parts = spec.split(":")
	if len(parts) != 3:
		raise ValueError("--profile debe ser `rol:capacidad:egress` (p.ej. worker:local-9b:none) o `full`")
	import sys as _sys

	_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
	from red_pill.harness.profile import resolve  # noqa: PLC0415 — import perezoso a propósito

	return resolve(parts[0], parts[1], parts[2])


def _version(anchor):
	return BLOCK_VERSION.get(anchor, 1)


def block_names(content):
	"""Anclas marcadas en `content`, en orden y con repeticiones (para auditar)."""
	return _ANY_BEGIN_RE.findall(content or "")


def prune_retired_blocks(path, backup=True):
	"""Quita los bloques de anclas retiradas de `path`. Devuelve los nombres podados."""
	path = os.path.expanduser(path) if path else path
	if not path or not os.path.exists(path):
		return []
	with open(path, encoding="utf-8") as f:
		content = f.read()
	pruned = [a for a in dict.fromkeys(block_names(content)) if a in RETIRED_ANCHORS]
	if not pruned:
		return []
	for a in pruned:
		content = _marker_re(a).sub("", content)
	content = re.sub(r"\n{3,}", "\n\n", content).strip()
	_atomic_write(path, content + "\n" if content else "", backup=backup)
	return pruned


# ── IDE → anchor-file registry (everything is merge; no "owner" files) ────────
@dataclass(frozen=True)
class AnchorTarget:
	ide: str
	path: str | None  # static path (with ~); None => resolved at runtime / not a file
	requires_workspace: bool  # path depends on --workspace
	scriptable: bool  # False => lives in app UI/DB, only --print


# OpenCode V2 sólo carga de forma nativa, y en CUALQUIER workspace, los
# `AGENTS.md` (global `~/.config/opencode/AGENTS.md` + los del árbol del
# workspace). Un `RED_PILL.md` suelto sólo entra por `instructions`, y ahí las
# rutas relativas se resuelven desde el workspace hacia arriba → en otro proyecto
# no se encuentra y OpenCode la ignora EN SILENCIO (regresión 2026-10-27: el
# handshake obligatorio desapareció del contexto tras la migración a V2).
# Fuente única del nombre: los injectors la importan de aquí.
OPENCODE_INSTRUCTIONS_FILE = "AGENTS.md"

ANCHOR_REGISTRY = [
	AnchorTarget("antigravity", "~/.gemini/GEMINI.md", False, True),  # user-level, global
	AnchorTarget("claude-code", "~/.claude/CLAUDE.md", False, True),  # user memory: global, cwd-independent
	AnchorTarget("claude-code-project", None, True, True),  # <workspace>/CLAUDE.md (project-scoped, opt-in)
	AnchorTarget("pi", None, True, True),  # <workspace>/AGENTS.override.md (project-scoped; shadows CLAUDE.md for Pi)
	AnchorTarget("claude-desktop-project", None, False, False),  # Project instructions: UI/DB, only --print
	AnchorTarget("opencode", "~/.config/opencode/AGENTS.md", False, True),  # user-level, global (V2 nativo)
]
REGISTRY_BY_IDE = {t.ide: t for t in ANCHOR_REGISTRY}


def _claude_desktop_present():
	for p in (
		"~/.config/Claude/claude_desktop_config.json",
		"~/Library/Application Support/Claude/claude_desktop_config.json",
		"~/AppData/Roaming/Claude/claude_desktop_config.json",
	):
		if os.path.exists(os.path.expanduser(p)):
			return True
	return False


def detect_present_ides(workspace):
	"""IDEs to target under --ide auto. antigravity + claude-code anchors are user-level/global
	(cwd-independent). claude-desktop-project is included when Desktop is installed so we can REMIND
	the user to paste it (its Project instructions aren't scriptable). claude-code-project is opt-in
	only (never auto): it would duplicate the handshake already in user memory. pi is workspace-scoped
	too (it writes <ws>/AGENTS.override.md, which SHADOWS CLAUDE.md for Pi only), so it needs
	--workspace and is skipped otherwise."""
	present = []
	if os.path.isdir(os.path.expanduser("~/.gemini")):
		present.append("antigravity")
	if os.path.isdir(os.path.expanduser("~/.claude")):
		present.append("claude-code")
	if _claude_desktop_present():
		present.append("claude-desktop-project")
	if os.path.isdir(os.path.expanduser("~/.config/opencode")):
		present.append("opencode")
	if workspace and os.path.isdir(os.path.expanduser("~/.pi/agent")):
		present.append("pi")
	return present


def resolve_target_path(target, workspace):
	if target.ide == "claude-code-project":
		return os.path.join(os.path.expanduser(workspace), "CLAUDE.md") if workspace else None
	if target.ide == "pi":
		# AGENTS.override.md REPLACES AGENTS.md/CLAUDE.md from that directory (pi ≥0.87).
		return os.path.join(os.path.expanduser(workspace), "AGENTS.override.md") if workspace else None
	return os.path.expanduser(target.path) if target.path else None


def ide_seed_path(seeds_dir: str, ide: str, anchor: str) -> str:
	"""Per-IDE seed override: seeds/<ide>/anchors/<anchor>.md wins over seeds/anchors/<anchor>.md."""
	override = os.path.join(os.path.dirname(seeds_dir), ide, "anchors", anchor + ".md")
	return override if os.path.exists(override) else os.path.join(seeds_dir, anchor + ".md")


# ── Variante del ancla de handshake: `hook` sólo donde alguien inyecta de verdad ──
# opencode (`redpill-harness.js`) y pi (`red-pill-context.ts`) traen su cliente de
# `/hook/context` en la propia siembra. Claude Code lo tiene por `settings.json`
# (`redpill_harness.py` en SessionStart/UserPromptSubmit): sembrar el ancla `hook`
# sin ese hook cableado deja la sesión SIN identidad —el ancla le dice al modelo
# que no la pida y nadie se la da—. Por eso se mira el cableado, no el nombre.
# `claude-desktop-project` (instrucciones de un Project del chat de Desktop) NO
# tiene hooks: la pestaña Code de Desktop es Claude Code y usa `~/.claude`.
HOOK_NATIVE = frozenset({"opencode", "pi"})
CLAUDE_HOOKED = frozenset({"claude-code", "claude-code-project"})
CLAUDE_HARNESS_HOOK = "redpill_harness.py"


def _settings_has_harness(path):
	try:
		with open(os.path.expanduser(path), encoding="utf-8") as f:
			hooks = json.load(f).get("hooks") or {}
	except (OSError, ValueError, AttributeError):
		return False
	if not isinstance(hooks, dict):
		return False
	events = set()
	for event, blocks in hooks.items():
		if not isinstance(blocks, list):
			continue
		for block in blocks:
			inner = block.get("hooks") if isinstance(block, dict) else None
			for h in inner if isinstance(inner, list) else []:
				if isinstance(h, dict) and CLAUDE_HARNESS_HOOK in str(h.get("command") or ""):
					events.add(event)
	# Sin SessionStart no hay identidad completa; sin UserPromptSubmit no hay turno.
	return {"SessionStart", "UserPromptSubmit"} <= events


def hook_wired(ide, workspace=None):
	"""¿Inyecta alguien la identidad en este arnés? Decide la variante `auto`."""
	if ide in HOOK_NATIVE:
		return True
	if ide not in CLAUDE_HOOKED:
		return False
	if not os.path.exists(os.path.expanduser(os.path.join("~/.claude/hooks", CLAUDE_HARNESS_HOOK))):
		return False
	candidates = ["~/.claude/settings.json"]
	if workspace:
		candidates += [os.path.join(workspace, ".claude", "settings.json"), os.path.join(workspace, ".claude", "settings.local.json")]
	return any(_settings_has_harness(p) for p in candidates)


def anchor_variant(ide, workspace=None, mode="auto"):
	"""`hook` (identidad inyectada por el arnés) o `prompt` (el modelo la pide)."""
	if mode in ("prompt", "hook"):
		return mode
	return "hook" if hook_wired(ide, workspace) else "prompt"


def anchor_seed_path(seeds_dir, ide, anchor, variant="prompt"):
	"""Seed de un ancla para un IDE: override propio > variante `hook` > genérico.

	La variante `<anchor>.hook.md` existe para las anclas que sobran cuando el arnés
	ya inyecta la identidad (handshake, pacto). Vive aquí, y no en cada inyector,
	porque opencode y pi siembran por su propio camino: antes sólo `main()` la
	aplicaba y el inyector de opencode devolvía el handshake a `prompt`.
	"""
	own = os.path.join(os.path.dirname(seeds_dir), ide, "anchors", anchor + ".md")
	if os.path.exists(own):
		return own
	if variant == "hook":
		hook_seed = os.path.join(seeds_dir, anchor + ".hook.md")
		if os.path.exists(hook_seed):
			return hook_seed
	return os.path.join(seeds_dir, anchor + ".md")


def ide_call_vars(ide):
	"""Per-IDE tool-call phrasing for the handshake (${RELAY_CALL}/${WAKE_CALL}).
	Antigravity is lax — the server's compatibility shim resolves the flat action name.
	Claude clients only call the ADVERTISED consolidated APIs, so they must use the
	`<api>` tool + an `action` argument (the flat name is not a tool for them).
	opencode does NOT prefix MCP tools — they appear under their resource
	group names (bunker_memory_api, swarm_orchestrator_api, etc.)."""
	# Antigravity has NO editor hooks — the handshake itself is the relay, and the
	# MODEL is the persistence carrier: debe devolver `continuity_id`/`mission_id`
	# del último `<session/>` que haya visto (sin hook no hay bridge que la capture).
	if ide == "antigravity":
		return {
			"RELAY_CALL": "`mcp_RedPill-Kernel_sovereign_handshake`",
			"WAKE_CALL": "`mcp_RedPill-Kernel_refresh_session_context`",
			"RELAY_INSTRUCTION": 'Call passing `user_prompt`, `previous_prompt` and `previous_response` (no editor hook — the handshake is the persistence relay). Also pass `originator` ("antigravity") and, when you have seen them in a previous response\'s `<session …/>` tag, echo back `continuity_id` and `mission_id` so the alma survives without a hook.',
		}
	# Pi **sí** tiene MCP desde 1.5.x (`~/.pi/agent/mcp.json`, `exposure`/`toolExposure`,
	# `pi.registerMcpServer()`). Lo que NO tiene es un hook de editor: su relay y su
	# identidad los sirven las extensiones (`red-pill-context.ts` para la identidad por
	# `context`; `red-pill.ts` para captura, RAG y ack). Corrección P4 (RFC-HARNESS-001).
	if ide == "pi":
		return {
			"RELAY_CALL": "el handshake automático de la extensión `red-pill.ts` (no hay tool que llamar)",
			"WAKE_CALL": "`bunker_search` para leer / `bunker_save` para escribir",
			"RELAY_INSTRUCTION": "No hace falta ninguna llamada: la extensión inyecta identidad/RAG y encola el turno automáticamente.",
		}
	# El chat de Claude Desktop (instrucciones de Project) no tiene hooks: como en
	# Antigravity, el handshake ES el relay y el turno sólo se guarda si viaja en él.
	if ide == "claude-desktop-project":
		return {
			"RELAY_CALL": "the `sovereign_handshake` tool",
			"WAKE_CALL": 'the `bunker_memory_api` tool with `{"action": "refresh_session_context", "payload": {}}`',
			"RELAY_INSTRUCTION": "Call passing `user_prompt`, `previous_prompt` and `previous_response` (no editor hook here — the handshake is the persistence relay).",
		}
	# Claude Code / OpenCode have editor hooks that capture prompt+response automatically.
	return {
		"RELAY_CALL": "the `sovereign_handshake` tool",
		"WAKE_CALL": 'the `bunker_memory_api` tool with `{"action": "refresh_session_context", "payload": {}}`',
		"RELAY_INSTRUCTION": "Call passing only `user_prompt` (the editor hook already captures prompt+response).",
	}


# ── Block construction + matching ─────────────────────────────────────────────
def _build_block(anchor, body, version):
	begin = "<!-- REDPILL:BEGIN %s v=%d -->" % (anchor, version)
	end = "<!-- REDPILL:END %s -->" % anchor
	return "%s\n%s\n%s" % (begin, body.strip(), end)


def _marker_re(anchor):
	a = re.escape(anchor)
	return re.compile(
		r"<!-- REDPILL:BEGIN %s(?: v=\d+)? -->.*?<!-- REDPILL:END %s -->" % (a, a),
		re.DOTALL,
	)


# Legacy (pre-marker) red-pill content to clean up during a one-time migration.
LEGACY_CONSTRAINT_NAMES = {
	"sovereign_handshake": "sovereign_handshake",
	"agent_core": "sovereign_atlas_awareness",
}
LEGACY_HEADING_RE = re.compile(r"^## (?:1\. Zero-Trust|2\. Model Change|3\. Persistent Memory).*\n?", re.MULTILINE)


def _legacy_constraint_re(name):
	return re.compile(
		r'<constraint\b[^>]*\bname="%s"[^>]*>.*?</constraint>[ \t]*\n?' % re.escape(name),
		re.DOTALL,
	)


def _backup_file(path):
	"""Respalda el contenido ANTERIOR antes de editar.

	- `<path>.bak`: copia PRISTINA (solo se crea una vez; nunca se pisa) — sirve
	para convivir con terceros y revertir al original del usuario.
	- `<path>.bak.<YYYYMMDD_HHMMSS>`: copia por edicion (historico).
	"""
	if not os.path.exists(path):
		return
	pristine = path + ".bak"
	if not os.path.exists(pristine):
		shutil.copy2(path, pristine)
	try:
		shutil.copy2(path, f"{path}.bak.{time.strftime('%Y%m%d_%H%M%S')}")
	except OSError:
		pass


def _atomic_write(path, content, backup=True):
	parent = os.path.dirname(os.path.abspath(path))
	os.makedirs(parent, exist_ok=True)
	if backup and os.path.exists(path):
		_backup_file(path)
	tmp = path + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		f.write(content)
	os.replace(tmp, path)


def _append_block(content, new_block):
	content = content.rstrip("\n")
	return (content + "\n\n" + new_block + "\n") if content else (new_block + "\n")


def splice_block(path, anchor, body, version, backup=True, update=False):
	"""Merge OUR marked region into `path`, preserving everything else.
	Returns one of: created | updated | unchanged | migrated."""
	new_block = _build_block(anchor, body, version)
	path = os.path.expanduser(path)

	if not os.path.exists(path):
		_atomic_write(path, new_block + "\n", backup=False)
		return "created"

	with open(path, encoding="utf-8") as f:
		content = f.read()

	mre = _marker_re(anchor)
	if mre.search(content):
		# Replace the first marked region; drop any accidental duplicates.
		state = {"n": 0}

		def _repl(_m):
			state["n"] += 1
			return new_block if state["n"] == 1 else ""

		new_content, _ = mre.subn(_repl, content)
		if new_content == content and not update:
			return "unchanged"
		_atomic_write(path, new_content, backup=backup)
		return "updated"

	# No marked region yet → migrate legacy red-pill content, else append.
	migrated = content
	if anchor == "sovereign_handshake":
		migrated = LEGACY_HEADING_RE.sub("", migrated)

	legacy_name = LEGACY_CONSTRAINT_NAMES.get(anchor)
	replaced = False
	if legacy_name:
		state = {"n": 0}

		def _repl_legacy(_m):
			# Replacement text is NOT re-scanned, so the new block (which may
			# contain the same constraint name) is safe from this regex.
			state["n"] += 1
			return (new_block + "\n") if state["n"] == 1 else ""

		migrated, count = _legacy_constraint_re(legacy_name).subn(_repl_legacy, migrated)
		replaced = count > 0

	if replaced:
		new_content = re.sub(r"\n{3,}", "\n\n", migrated)
		_atomic_write(path, new_content, backup=backup)
		return "migrated"

	_atomic_write(path, _append_block(migrated, new_block), backup=backup)
	return "migrated" if migrated != content else "appended"


def remove_block(path, anchor, backup=True):
	"""Remove OUR marked region only. Delete the file if nothing else remains."""
	path = os.path.expanduser(path)
	if not os.path.exists(path):
		return "absent"
	with open(path, encoding="utf-8") as f:
		content = f.read()
	mre = _marker_re(anchor)
	if not mre.search(content):
		return "absent"
	new_content = re.sub(r"\n{3,}", "\n\n", mre.sub("", content)).strip()
	if not new_content:
		if backup:
			shutil.copy2(path, path + ".bak")
		os.remove(path)
		return "removed-file"
	_atomic_write(path, new_content + "\n", backup=backup)
	return "removed-block"


def splice_ide(
	ide,
	anchors,
	seeds_dir,
	workspace,
	variables,
	backup=True,
	update=False,
	remove=False,
	mode="auto",
	prune=(),
	known_blocks=None,
):
	"""Splice (or remove) the anchors for one IDE. Returns the number of blocks written/modified.

	Shared by ``main()`` and the per-IDE adapters (e.g. ``scripts/inject/pi``) so the
	per-IDE seed override + ``ide_call_vars`` resolution lives in exactly one place.

	`prune` son anclas conocidas que NO van en `anchors` y deben salir del fichero.
	Es lo que hace posible el filtro por rol: opencode sustituye su roster fijo por
	los `rules_blocks` del bundle y poda el resto en la misma pasada.
	"""
	target = REGISTRY_BY_IDE[ide]
	path = resolve_target_path(target, workspace)
	if target.requires_workspace and not workspace:
		logger.warning(f"• {ide}: requiere --workspace; omitido.")
		return 0
	changed = 0
	variant = anchor_variant(ide, workspace, mode)
	for a in prune:
		if a in anchors:
			continue
		status = remove_block(path, a, backup=backup)
		if status not in ("unchanged", "absent"):
			changed += 1
		logger.info(f"✓ {ide}:{a} [{path}] → {status} (fuera del rol)")
	for a in anchors:
		if remove:
			status = remove_block(path, a, backup=backup)
		else:
			with open(anchor_seed_path(seeds_dir, ide, a, variant), encoding="utf-8") as f:
				body = subst(f.read(), {**variables, **ide_call_vars(ide)})
			status = splice_block(path, a, body, _version(a), backup=backup, update=update)
		if status not in ("unchanged", "absent"):
			changed += 1
		logger.info(f"✓ {ide}:{a} [{path}] → {status}")
	if not remove:
		changed += _log_pruned(ide, path, prune_retired_blocks(path, backup=backup))
		if known_blocks is not None:
			changed += _log_pruned(ide, path, prune_blocks_not_in(path, known_blocks, backup=backup))
	return changed


def prune_blocks_not_in(path, keep, backup=True):
	"""Poda las anclas conocidas que no están en `keep`. Devuelve las podadas.

	El destino de las anclas es un fichero compartido (un `AGENTS.md` para todos los
	roles de un arnés no puede tener las reglas de varios a la vez). Por eso sembrar
	un rol **sustituye** el juego anterior: las que sobran se retiran en la misma
	pasada en vez de quedar huérfanas.
	"""
	path = os.path.expanduser(path)
	if not os.path.exists(path):
		return []
	try:
		with open(path, encoding="utf-8") as f:
			present = set(block_names(f.read()))
	except OSError:
		return []
	pruned = [a for a in sorted(present & KNOWN_BLOCKS) if a not in set(keep)]
	if not pruned:
		return []
	with open(path, encoding="utf-8") as f:
		content = f.read()
	for a in pruned:
		content = re.sub(r"\n{3,}", "\n\n", _marker_re(a).sub("", content)).strip()
	if not content:
		if backup:
			shutil.copy2(path, path + ".bak")
		os.remove(path)
	else:
		_atomic_write(path, content + "\n", backup=backup)
	return pruned


def _log_pruned(ide, path, pruned):
	for a in pruned:
		logger.info(f"✓ {ide}:{a} [{path}] → retirado (ancla fuera del roster)")
	return len(pruned)


def _csv(value):
	return [x.strip() for x in value.split(",") if x.strip()]


def main():
	parser = argparse.ArgumentParser(description="Inject/merge red-pill anchor blocks into IDE instruction files.")
	parser.add_argument("--ide", default="auto", help="csv: auto|all|antigravity|claude-code|claude-code-project|pi|claude-desktop-project|opencode")
	parser.add_argument(
		"--anchor",
		default=",".join(BLOCK_ANCHORS),
		help="csv of anchor seeds to inject (file names in --seeds-dir)",
	)
	parser.add_argument(
		"--workspace", help="Workspace root: resolves ${WORKSPACE} and targets Claude Code <ws>/CLAUDE.md or Pi <ws>/AGENTS.override.md"
	)
	parser.add_argument("--redpill-dir", help="Red Pill source dir (resolves ${REDPILL_DIR}).")
	parser.add_argument("--uv-path", help="Path to uv (shared build_vars; current anchors don't use it).")
	parser.add_argument("--seeds-dir", help="Dir with <anchor>.md seeds. Default: ../seeds/anchors next to this script.")
	parser.add_argument("--update", action="store_true", help="Rewrite the block even if unchanged.")
	parser.add_argument("--no-backup", action="store_true", help="Do not write a .bak before modifying.")
	parser.add_argument(
		"--mode",
		default="auto",
		choices=["auto", "prompt", "hook"],
		help="Variante del block de handshake: `hook` (identidad inyectada por el arnés), `prompt` (el modelo llama a la tool) o `auto` (hook donde el arnés lo soporte).",
	)
	parser.add_argument(
		"--prune-unlisted",
		action="store_true",
		help="Retira las anclas conocidas que NO están en --anchor. Para siembras por rol: el destino es un fichero compartido y el rol vigente manda.",
	)
	parser.add_argument(
		"--profile",
		default=None,
		help="Perfil `rol:capacidad:egress`: sus `rules_blocks` manda sobre --anchor (sustituye, no suma) y el resto de anclas conocidas se poda.",
	)
	parser.add_argument("--print", dest="print_only", action="store_true", help="Print resolved anchor(s) to stdout; touch no files.")
	parser.add_argument("--remove", action="store_true", help="Remove red-pill anchor block(s) instead of writing.")
	args = parser.parse_args()

	if args.seeds_dir:
		seeds_dir = os.path.abspath(os.path.expanduser(args.seeds_dir))
	else:
		seeds_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "seeds", "anchors"))

	anchors = _csv(args.anchor)
	prune_unlisted = args.prune_unlisted
	if args.profile:
		# El perfil manda: `rules_blocks` del rol sustituye la lista de anclas.
		# Un rol sin `rules_blocks` (p. ej. `none`) significa roster completo, no
		# "ninguna ancla": es la instalación estándar, no una instalación desnuda.
		try:
			bundle = resolve_profile(args.profile)
		except ValueError as exc:
			parser.error(str(exc))
		if bundle is not None:
			anchors = list(bundle.rules_blocks) or list(BLOCK_ANCHORS)
			prune_unlisted = True
			logger.info(f"perfil {bundle.role} × {bundle.capability} × {bundle.egress} → anclas: {', '.join(anchors)}")
	if not anchors and not args.remove:
		parser.error("--anchor vacío (¿perfil sin rules_blocks?)")
	if not args.remove:
		for a in anchors:
			seed = os.path.join(seeds_dir, a + ".md")
			if not os.path.exists(seed):
				parser.error(f"seed no encontrado para anchor '{a}': {seed}")

	tokens = _csv(args.ide)
	if "auto" in tokens:
		ides = detect_present_ides(args.workspace)
	elif "all" in tokens:
		ides = [t.ide for t in ANCHOR_REGISTRY]
	else:
		ides = []
		for tok in tokens:
			if tok not in REGISTRY_BY_IDE:
				parser.error(f"IDE desconocido: {tok}")
			ides.append(tok)

	if not ides:
		logger.warning("No hay IDEs objetivo (¿falta --workspace para claude-code?). Nada que hacer.")
		return

	variables = build_vars(args)
	variables.update(agent_core_vars())

	def _body(ide: str, anchor: str) -> str:
		with open(anchor_seed_path(seeds_dir, ide, anchor, anchor_variant(ide, args.workspace, args.mode)), encoding="utf-8") as f:
			return f.read()

	backup = not args.no_backup
	changed = 0
	reminders = 0
	for ide in ides:
		target = REGISTRY_BY_IDE[ide]
		path = resolve_target_path(target, args.workspace)
		# Resolve bodies per-IDE: seeds/<ide>/anchors/<anchor>.md overrides the generic seed,
		# and ${RELAY_CALL}/${WAKE_CALL} differ by client (see ide_call_vars).
		bodies = {a: subst(_body(ide, a), {**variables, **ide_call_vars(ide)}) for a in anchors} if not args.remove else {}

		# Non-scriptable target (Claude Desktop Project instructions live in the app UI/DB).
		if not target.scriptable:
			if args.remove:
				logger.warning(f"• {ide}: --remove no aplica (no es un fichero); omitido.")
				continue
			if args.print_only:
				print(f"\n===== ANCHOR · {ide} (paste into Project instructions) =====")
				print("\n\n".join(_build_block(a, bodies[a], _version(a)) for a in anchors))
			else:
				logger.warning(
					f"• {ide}: RECORDATORIO — las instrucciones del Project de Claude Desktop NO son "
					f"scriptables (viven en la app). Pégalas a mano en Claude Desktop → Projects → tu "
					f"proyecto → Instrucciones. Obtén el texto con:\n"
					f"    uv run python scripts/inject_anchor.py --ide {ide} --print"
				)
				reminders += 1
			continue

		# Forced preview of a scriptable target.
		if args.print_only:
			print(f"\n===== ANCHOR · {ide} (preview) =====")
			print("\n\n".join(_build_block(a, bodies[a], _version(a)) for a in anchors))
			continue

		if target.requires_workspace and not args.workspace:
			logger.warning(f"• {ide}: requiere --workspace; omitido.")
			continue

		for a in anchors:
			if args.remove:
				status = remove_block(path, a, backup=backup)
			else:
				status = splice_block(path, a, bodies[a], _version(a), backup=backup, update=args.update)
			if status not in ("unchanged", "absent"):
				changed += 1
			logger.info(f"✓ {ide}:{a} [{path}] → {status}")
		if not args.remove:
			changed += _log_pruned(ide, path, prune_retired_blocks(path, backup=backup))
			if prune_unlisted:
				changed += _log_pruned(ide, path, prune_blocks_not_in(path, anchors, backup=backup))

	tail = f" · {reminders} recordatorio(s) de pegado manual" if reminders else ""
	logger.info(f"Hecho. {changed} bloque(s) escrito(s)/modificado(s){tail}.")


if __name__ == "__main__":
	main()
