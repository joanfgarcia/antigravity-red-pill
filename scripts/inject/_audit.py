"""Auditoría de convivencia de la siembra: foto antes/después y hallazgos.

red-pill es invitado en ficheros que comparte con otros arneses y con la mano del
Operador (``settings.json``, ``CLAUDE.md``, ``AGENTS.md``, configs MCP). La siembra
sólo toca lo suyo, pero «lo suyo» puede convivir con algo que lo duplica o lo
contradice: un hook de otro arnés que también inyecta contexto, un bloque de ancla
copiado a mano en un ``CLAUDE.md`` de proyecto, el MCP registrado en dos ámbitos.
Nada de eso se arregla solo, y borrarlo sin preguntar rompería al otro.

Este módulo no escribe en ninguna config. Hace tres cosas:

- ``snapshot``: foto de todo lo que la siembra puede tocar (copia en ``before/``,
	para poder volver atrás a mano).
- ``audit``: hallazgos de convivencia (``error`` / ``warn`` / ``info``).
- ``write_report``: diff antes→después + hallazgos en ``REPORT.md``.

``inject_cli.py`` lo corre alrededor de cada siembra (install, ``upgrade.sh`` y
``red-pill bunker update`` pasan todos por ahí) y ``--check`` lo corre solo.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import time
from collections import Counter
from dataclasses import dataclass

from inject_anchor import (
	ANCHOR_REGISTRY,
	BLOCK_ANCHORS,
	RETIRED_ANCHORS,
	block_names,
	hook_wired,
)
from inject_settings import HOOK_MANIFEST, _is_managed_block

ERROR, WARN, INFO = "error", "warn", "info"
REDPILL_SERVER = "RedPill-Kernel"
CONTEXT_EVENTS = ("SessionStart", "UserPromptSubmit")
KEEP_RUNS = 10
BACKUP_PILEUP = 10
DIFF_MAX_LINES = 400

SCRIPTS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
SEED_ANCHORS = os.path.join(REPO_ROOT, "seeds", "anchors")
SEED_HOOKS = os.path.join(REPO_ROOT, "seeds", "settings", "hooks")

_SCRIPT_RE = re.compile(r"redpill_[\w.-]*\.py")
_MARKED_RE = re.compile(r"<!-- REDPILL:BEGIN (\S+)(?: v=\d+)? -->.*?<!-- REDPILL:END \1 -->", re.DOTALL)
_CONSTRAINT_RE = re.compile(r'<constraint\b[^>]*\bname="([\w-]+)"')


@dataclass(frozen=True)
class Finding:
	level: str
	code: str
	where: str
	message: str


# ── Rutas ─────────────────────────────────────────────────────────────────────
def _home(path: str) -> str:
	return os.path.expanduser(path)


def _short(path: str) -> str:
	home = os.path.expanduser("~")
	return "~" + path[len(home) :] if path.startswith(home + os.sep) else path


def _state_dir() -> str:
	base = os.environ.get("XDG_DATA_HOME") or _home("~/.local/share")
	return os.path.join(base, "red-pill", "state", "inject")


def workspace_roots(workspace: str | None = None) -> list[str]:
	"""Raíces a revisar: la del ``--workspace`` y todas las del registro."""
	roots: list[str] = []
	if workspace:
		roots.append(os.path.abspath(_home(workspace)))
	registry = _home("~/.config/red-pill/workspaces.yaml")
	try:
		import yaml

		with open(registry, encoding="utf-8") as f:
			data = yaml.safe_load(f) or {}
	except Exception:
		data = {}
	for entry in data.get("workspaces") or [] if isinstance(data, dict) else []:
		root = entry.get("root") if isinstance(entry, dict) else None
		if root:
			resolved = os.path.abspath(_home(str(root)))
			if resolved not in roots and os.path.isdir(resolved):
				roots.append(resolved)
	return roots


def anchor_files(roots: list[str]) -> list[str]:
	files = [_home(t.path) for t in ANCHOR_REGISTRY if t.path and t.scriptable]
	for root in roots:
		files += [os.path.join(root, "CLAUDE.md"), os.path.join(root, "AGENTS.override.md")]
	return files


def settings_files(roots: list[str]) -> list[str]:
	files = [_home("~/.claude/settings.json")]
	for root in roots:
		files += [os.path.join(root, ".claude", "settings.json"), os.path.join(root, ".claude", "settings.local.json")]
	return files


def mcp_files(roots: list[str]) -> list[str]:
	files = [
		_home("~/.gemini/config/mcp_config.json"),
		_home("~/.gemini/antigravity/mcp_config.json"),
		_home("~/.config/Claude/claude_desktop_config.json"),
		_home("~/.config/opencode/opencode.json"),
		_home("~/.config/opencode/opencode.jsonc"),
		_home("~/.pi/agent/mcp.json"),
	]
	return files + [os.path.join(root, ".mcp.json") for root in roots]


def _hooks_dir() -> str:
	return _home("~/.claude/hooks")


def _claude_json() -> str:
	return _home("~/.claude.json")


# ── Lectura tolerante ─────────────────────────────────────────────────────────
def _read(path: str) -> str | None:
	try:
		with open(path, encoding="utf-8") as f:
			return f.read()
	except (OSError, UnicodeDecodeError):
		return None


def _json(path: str) -> dict:
	text = _read(path)
	if not text:
		return {}
	try:
		data = json.loads(text)
	except ValueError:
		return {}
	return data if isinstance(data, dict) else {}


def _sha(text: str) -> str:
	return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _expand_cmd(cmd: str) -> str:
	home = os.path.expanduser("~")
	return cmd.replace("${HOME}", home).replace("$HOME", home).replace("~/", home + "/")


# ── Foto ──────────────────────────────────────────────────────────────────────
def _claude_json_view() -> str | None:
	"""``~/.claude.json`` es estado de la app (MBs, cambia solo): sólo interesa el MCP."""
	if not os.path.exists(_claude_json()):
		return None
	data = _json(_claude_json())
	projects = {p: v["mcpServers"] for p, v in (data.get("projects") or {}).items() if isinstance(v, dict) and v.get("mcpServers")}
	return json.dumps({"mcpServers": data.get("mcpServers") or {}, "projects.mcpServers": projects}, indent=2, sort_keys=True) + "\n"


def _hooks_view() -> str | None:
	d = _hooks_dir()
	if not os.path.isdir(d):
		return None
	lines = []
	for name in sorted(os.listdir(d)):
		path = os.path.join(d, name)
		if os.path.isfile(path):
			text = _read(path)
			lines.append(f"{name}  {_sha(text)[:12] if text is not None else '?'}")
	return "\n".join(lines) + "\n"


def snapshot(workspace: str | None = None) -> dict[str, str | None]:
	"""Ruta → contenido (``None`` si no existe) de todo lo que la siembra puede tocar."""
	roots = workspace_roots(workspace)
	snap: dict[str, str | None] = {}
	for path in dict.fromkeys(anchor_files(roots) + settings_files(roots) + mcp_files(roots)):
		snap[path] = _read(path)
	snap[_claude_json() + "#mcp"] = _claude_json_view()
	snap[_hooks_dir() + "/"] = _hooks_view()
	return snap


def save_snapshot(snap: dict[str, str | None], dest: str) -> None:
	"""Copia la foto en ``dest`` (un fichero por ruta + ``index.json``) para volver atrás."""
	os.makedirs(dest, exist_ok=True)
	index = {}
	for i, (path, text) in enumerate(sorted(snap.items())):
		if text is None:
			continue
		name = f"{i:02d}_" + re.sub(r"[^\w.-]+", "_", _short(path)).strip("_")
		with open(os.path.join(dest, name), "w", encoding="utf-8") as f:
			f.write(text)
		index[name] = path
	with open(os.path.join(dest, "index.json"), "w", encoding="utf-8") as f:
		json.dump(index, f, indent=2, sort_keys=True)


def diff(before: dict[str, str | None], after: dict[str, str | None]) -> dict[str, list[str]]:
	"""Ruta → diff unificado de lo que cambió (vacío si nada)."""
	out: dict[str, list[str]] = {}
	for path in sorted(set(before) | set(after)):
		a, b = before.get(path), after.get(path)
		if a == b:
			continue
		lines = list(
			difflib.unified_diff(
				(a or "").splitlines(keepends=True),
				(b or "").splitlines(keepends=True),
				fromfile=f"antes:{_short(path)}" if a is not None else "/dev/null",
				tofile=f"después:{_short(path)}" if b is not None else "/dev/null",
			)
		)
		out[path] = lines
	return out


# ── Hallazgos ─────────────────────────────────────────────────────────────────
def _iter_hooks(settings: dict):
	hooks = settings.get("hooks")
	if not isinstance(hooks, dict):
		return
	for event, blocks in hooks.items():
		if not isinstance(blocks, list):
			continue
		for block in blocks:
			inner = block.get("hooks") if isinstance(block, dict) else None
			for h in inner if isinstance(inner, list) else []:
				if isinstance(h, dict) and isinstance(h.get("command"), str):
					yield event, block, h["command"]


def _audit_settings(roots: list[str]) -> list[Finding]:
	found: list[Finding] = []
	user_path = _home("~/.claude/settings.json")
	user_scripts: set[tuple[str, str]] = set()
	for path in settings_files(roots):
		settings = _json(path)
		if not settings:
			continue
		where = _short(path)
		is_user = path == user_path
		seen: Counter = Counter()
		for event, block, cmd in _iter_hooks(settings):
			script = _SCRIPT_RE.search(cmd)
			if not script:
				if event in CONTEXT_EVENTS:
					found.append(
						Finding(
							INFO,
							"foreign_context_hook",
							where,
							f"{event} ejecuta `{cmd}` (no es de red-pill). Si inyecta identidad, reglas o telemetría, "
							"puede duplicar o contradecir lo que inyecta el arnés: revísalo antes y después de la siembra.",
						)
					)
				continue
			name = script.group(0)
			seen[(event, name)] += 1
			if is_user:
				user_scripts.add((event, name))
			if not _is_managed_block(block):
				found.append(
					Finding(
						WARN,
						"hook_mixed_block",
						where,
						f"{event}: `{name}` comparte bloque con comandos ajenos. La siembra no lo toca (no es sólo suyo): "
						"no se actualizará ni se podará. Sepáralo o quítalo a mano.",
					)
				)
			target = _expand_cmd(cmd)
			deployed = os.path.join(_hooks_dir(), name)
			if f"/.claude/hooks/{name}" in target and not os.path.exists(deployed):
				found.append(
					Finding(
						ERROR, "hook_script_missing", where, f"{event} llama a `{_short(deployed)}`, que no existe: el hook falla en cada evento."
					)
				)
			if not is_user and (event, name) in user_scripts:
				found.append(
					Finding(
						WARN,
						"hook_duplicate_scope",
						where,
						f"{event}: `{name}` también está en ~/.claude/settings.json; Claude Code los suma y se ejecuta dos veces. Quítalo del proyecto.",
					)
				)
		for (event, name), n in seen.items():
			if n > 1:
				found.append(Finding(WARN, "hook_duplicate", where, f"{event}: `{name}` aparece {n} veces en el mismo fichero."))
	return found


def _seed_heading(name: str) -> str | None:
	text = _read(os.path.join(SEED_ANCHORS, name))
	if not text:
		return None
	return next((ln.strip() for ln in text.splitlines() if ln.startswith("## ")), None)


def _handshake_variant(content: str) -> str | None:
	m = re.search(r"<!-- REDPILL:BEGIN sovereign_handshake(?: v=\d+)? -->(.*?)<!-- REDPILL:END sovereign_handshake -->", content, re.DOTALL)
	if not m:
		return None
	hook, prompt = _seed_heading("sovereign_handshake.hook.md"), _seed_heading("sovereign_handshake.md")
	if hook and hook in m.group(1):
		return "hook"
	if prompt and prompt in m.group(1):
		return "prompt"
	return "?"


def _audit_anchors(roots: list[str]) -> list[Finding]:
	found: list[Finding] = []
	global_claude = _home("~/.claude/CLAUDE.md")
	global_has = bool(block_names(_read(global_claude) or ""))
	for path in anchor_files(roots):
		content = _read(path)
		if content is None:
			continue
		where = _short(path)
		names = block_names(content)
		for name, n in Counter(names).items():
			if n > 1:
				found.append(Finding(WARN, "anchor_duplicate", where, f"el bloque `{name}` está {n} veces; la siembra deja uno."))
			if name in RETIRED_ANCHORS:
				found.append(Finding(WARN, "anchor_retired", where, f"bloque `{name}` retirado del roster: la siembra lo poda."))
			elif name not in BLOCK_ANCHORS:
				found.append(
					Finding(
						WARN,
						"anchor_unknown",
						where,
						f"bloque REDPILL `{name}` que esta versión no siembra. Si es de otro sembrador, ignóralo; si es un resto, bórralo a mano.",
					)
				)
		unmarked = [n for n in _CONSTRAINT_RE.findall(_MARKED_RE.sub("", content)) if n in BLOCK_ANCHORS or n in RETIRED_ANCHORS]
		for name in dict.fromkeys(unmarked):
			found.append(
				Finding(
					WARN,
					"anchor_unmarked",
					where,
					f"regla `{name}` de red-pill fuera de las marcas REDPILL: la siembra no la actualiza y convive con la marcada (dos versiones de la misma regla).",
				)
			)
		if path.endswith(os.sep + "CLAUDE.md") and path != global_claude and names and global_has:
			found.append(
				Finding(
					WARN,
					"anchor_project_duplicate",
					where,
					"lleva anclas de red-pill y ~/.claude/CLAUDE.md también: Claude Code carga las dos y la sesión las ve duplicadas.",
				)
			)
		if path == global_claude and _handshake_variant(content) == "hook" and not hook_wired("claude-code"):
			found.append(
				Finding(
					ERROR,
					"anchor_hook_unwired",
					where,
					"el handshake está en variante `hook` pero `redpill_harness.py` no está cableado en SessionStart/UserPromptSubmit: la sesión arranca sin identidad.",
				)
			)
		pile = (
			[f for f in os.listdir(os.path.dirname(path)) if f.startswith(os.path.basename(path) + ".bak.")]
			if os.path.isdir(os.path.dirname(path))
			else []
		)
		if len(pile) > BACKUP_PILEUP:
			found.append(
				Finding(
					INFO,
					"backup_pileup",
					where,
					f"{len(pile)} respaldos `.bak.<fecha>` acumulados al lado; el `.bak` prístino basta para volver al original.",
				)
			)
	return found


def _audit_mcp(roots: list[str]) -> list[Finding]:
	found: list[Finding] = []
	data = _json(_claude_json())
	user = REDPILL_SERVER in (data.get("mcpServers") or {})
	for project, entry in (data.get("projects") or {}).items():
		if isinstance(entry, dict) and REDPILL_SERVER in (entry.get("mcpServers") or {}) and user:
			found.append(
				Finding(
					WARN,
					"mcp_multi_scope",
					"~/.claude.json",
					f"`{REDPILL_SERVER}` está a nivel de usuario y también en el proyecto `{project}`: dos conexiones al kernel.",
				)
			)
	for root in roots:
		path = os.path.join(root, ".mcp.json")
		if user and REDPILL_SERVER in (_json(path).get("mcpServers") or {}):
			found.append(
				Finding(WARN, "mcp_multi_scope", _short(path), f"`{REDPILL_SERVER}` también está en ~/.claude.json: Claude Code ve dos servidores.")
			)
	return found


def _audit_hook_dir() -> list[Finding]:
	d = _hooks_dir()
	if not os.path.isdir(d):
		return []
	found: list[Finding] = []
	seeded = set(os.listdir(SEED_HOOKS)) if os.path.isdir(SEED_HOOKS) else set()
	manifest = _json(os.path.join(d, HOOK_MANIFEST))
	backups = []
	for name in sorted(os.listdir(d)):
		path = os.path.join(d, name)
		if not os.path.isfile(path):
			continue
		if ".bak" in name:
			backups.append(name)
			continue
		if not re.fullmatch(r"redpill_[\w.-]*\.py", name):
			continue
		if name not in seeded:
			found.append(
				Finding(
					WARN, "hook_stale_script", _short(path), "script de red-pill que la semilla ya no trae: la siembra lo retira a `.bak.<fecha>`."
				)
			)
			continue
		text = _read(path)
		if manifest.get(name) and text is not None and manifest[name] != _sha(text):
			found.append(
				Finding(WARN, "hook_edited", _short(path), "difiere de lo que sembró red-pill (¿editado a mano?): la siembra lo respalda y lo pisa.")
			)
	if backups:
		found.append(
			Finding(
				INFO,
				"hook_backups",
				_short(d),
				f"{len(backups)} respaldo(s) ({', '.join(backups[:4])}{'…' if len(backups) > 4 else ''}): bórralos cuando ya no hagan falta.",
			)
		)
	return found


def audit(workspace: str | None = None) -> list[Finding]:
	roots = workspace_roots(workspace)
	findings = _audit_settings(roots) + _audit_anchors(roots) + _audit_mcp(roots) + _audit_hook_dir()
	order = {ERROR: 0, WARN: 1, INFO: 2}
	return sorted(findings, key=lambda f: (order[f.level], f.where, f.code))


# ── Salida ────────────────────────────────────────────────────────────────────
_ICON = {ERROR: "✗", WARN: "⚠", INFO: "·"}


def format_findings(findings: list[Finding]) -> str:
	if not findings:
		return "  sin hallazgos de convivencia."
	return "\n".join(f"  {_ICON[f.level]} [{f.level}] {f.where}: {f.message} ({f.code})" for f in findings)


def new_run_dir() -> str:
	path = os.path.join(_state_dir(), time.strftime("%Y%m%d_%H%M%S"))
	os.makedirs(path, exist_ok=True)
	return path


def prune_runs(keep: int = KEEP_RUNS) -> None:
	base = _state_dir()
	if not os.path.isdir(base):
		return
	runs = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
	for d in runs[:-keep] if keep > 0 else runs:
		shutil.rmtree(os.path.join(base, d), ignore_errors=True)


def write_report(run_dir: str, pre: list[Finding], post: list[Finding], changes: dict[str, list[str]]) -> str:
	parts = [
		"# Siembra de red-pill — antes y después",
		"",
		"Copia de lo que había antes: `before/` (`index.json` dice a qué ruta va cada fichero).",
		"",
		"## Hallazgos antes de sembrar",
		"",
		format_findings(pre),
		"",
		"## Hallazgos después de sembrar",
		"",
		format_findings(post),
		"",
		f"## Cambios ({len(changes)} fichero(s))",
		"",
	]
	for path, lines in changes.items():
		parts += [f"### {_short(path)}", "", "```diff"]
		parts += [ln.rstrip("\n") for ln in lines[:DIFF_MAX_LINES]]
		if len(lines) > DIFF_MAX_LINES:
			parts.append(f"… ({len(lines) - DIFF_MAX_LINES} líneas más)")
		parts += ["```", ""]
	report = os.path.join(run_dir, "REPORT.md")
	with open(report, "w", encoding="utf-8") as f:
		f.write("\n".join(parts) + "\n")
	return report


def summarize_changes(changes: dict[str, list[str]]) -> str:
	if not changes:
		return "  ningún fichero cambió."
	rows = []
	for path, lines in changes.items():
		plus = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
		minus = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
		rows.append(f"  {_short(path)}  (+{plus} −{minus})")
	return "\n".join(rows)
