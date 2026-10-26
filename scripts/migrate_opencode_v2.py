#!/usr/bin/env python3
"""Migrate an OpenCode V1 ``opencode.jsonc`` to the OpenCode V2 config schema.

Config-only migration. It rewrites the keys RedPill owns (plus the shapes V2
changed), preserves foreign keys, and is idempotent: a second run is a no-op.

V1 -> V2 changes applied (see opencode.ai/v2/docs and migrate-v1):

  plugin[]         -> plugins[]              (single-file paths are skipped by V2;
                                              files under a discovered plugins/
                                              dir are dropped and auto-discovered)
  mcp.<name>       -> mcp.servers.<name>     (+ enabled:false -> disabled:true,
                                              integer timeout -> {catalog,execution})
  skills.paths[]   -> skills[]               (paths + urls combined)
  permission{}     -> permissions[]          (last-match-wins; catch-all first,
                                              task->subagent, bash->shell,
                                              write/patch->edit; tools map)
  provider{}       -> providers{}            (npm->package, api/options->settings,
                                              model shape -> capabilities/variants)
  default          -> model                  (root default block removed)
  disabled_providers[] -> policies[]         (provider.use deny)
  enabled_providers[]  -> policies[]         (deny * + allow each)

Plugin *code* is NOT migrated here: V1 plugin implementations do not run in V2
(see opencode.ai/v2/docs/build/plugins/migrate-v1). The RedPill scribe plugin in
``seeds/opencode/plugins/redpill-scribe.js`` already ships a dual v1/v2 entrypoint.

Usage:
    python scripts/migrate_opencode_v2.py --dry-run
    python scripts/migrate_opencode_v2.py --config ~/.config/opencode/opencode.jsonc
    python scripts/migrate_opencode_v2.py --config X --output Y --no-backup
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone

logger = logging.getLogger("opencode_v2_migrator")

# Reuse the shared JSONC stripper when available (scripts/ lives beside us).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
	from _config_common import strip_jsonc_comments  # noqa: E402
except Exception:  # pragma: no cover - standalone fallback
	strip_jsonc_comments = None

DEFAULT_CONFIG = "~/.config/opencode/opencode.jsonc"

# V1 runtime package -> V2 provider package (opencode.ai/v2/docs/providers).
NPM_PACKAGE_MAP = {
	"@ai-sdk/openai-compatible": "@opencode/ai/providers/openai-compatible",
	"@ai-sdk/openai": "@opencode/ai/providers/openai",
	"@ai-sdk/anthropic": "@opencode/ai/providers/anthropic",
	"@ai-sdk/google": "@opencode/ai/providers/google",
	"@ai-sdk/google-vertex": "@opencode/ai/providers/google-vertex",
	"@ai-sdk/xai": "@opencode/ai/providers/xai",
}

# V1 permission action -> V2 action (opencode.ai/v2/docs/permissions).
ACTION_ALIAS = {"task": "subagent", "bash": "shell", "write": "edit", "patch": "edit"}

V1_KEYS = ("plugin", "permission", "provider", "default", "disabled_providers", "enabled_providers")

# Model keys already mapped explicitly, so not copied blindly as unknown.
_MODEL_HANDLED = {
	"modelID",
	"id",
	"name",
	"family",
	"releaseDate",
	"release_date",
	"package",
	"settings",
	"options",
	"headers",
	"body",
	"compatibility",
	"cost",
	"limit",
	"disabled",
	"status",
	"capabilities",
	"variants",
	"tool_call",
	"attachment",
	"reasoning",
	"modalities",
	"temperature",
}


# ── JSONC parsing ─────────────────────────────────────────────────────────────
def _strip_comments(text: str) -> str:
	return strip_jsonc_comments(text) if strip_jsonc_comments else _strip_comments_fallback(text)


def _strip_comments_fallback(text: str) -> str:
	"""String-aware // and /* */ stripper (used only if _config_common is absent)."""
	out = []
	i, n = 0, len(text)
	in_str = esc = False
	while i < n:
		c = text[i]
		if in_str:
			out.append(c)
			if esc:
				esc = False
			elif c == "\\":
				esc = True
			elif c == '"':
				in_str = False
			i += 1
			continue
		if c == '"':
			in_str = True
			out.append(c)
			i += 1
			continue
		if c == "/" and i + 1 < n and text[i + 1] == "/":
			while i < n and text[i] != "\n":
				i += 1
			continue
		if c == "/" and i + 1 < n and text[i + 1] == "*":
			i += 2
			while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
				i += 1
			i += 2
			continue
		out.append(c)
		i += 1
	return "".join(out)


def _strip_trailing_commas(text: str) -> str:
	"""Remove JSONC trailing commas (string-aware)."""
	out = []
	i, n = 0, len(text)
	in_str = esc = False
	while i < n:
		c = text[i]
		if in_str:
			out.append(c)
			if esc:
				esc = False
			elif c == "\\":
				esc = True
			elif c == '"':
				in_str = False
			i += 1
			continue
		if c == '"':
			in_str = True
			out.append(c)
			i += 1
			continue
		if c == ",":
			j = i + 1
			while j < n and text[j] in " \t\r\n":
				j += 1
			if j < n and text[j] in "}]":
				i += 1
				continue
		out.append(c)
		i += 1
	return "".join(out)


def load_jsonc(path: str) -> dict:
	raw = open(path, "r", encoding="utf-8").read()
	stripped = _strip_trailing_commas(_strip_comments(raw))
	try:
		return json.loads(stripped)
	except json.JSONDecodeError as exc:
		raise SystemExit(f"error: cannot parse {path}: {exc}") from exc


# ── plugin dirs ───────────────────────────────────────────────────────────────
def _global_config_dirs() -> list[str]:
	dirs = [os.path.realpath(os.path.expanduser("~/.config/opencode")), os.path.realpath("/etc/opencode")]
	xdg = os.environ.get("XDG_CONFIG_HOME")
	if xdg:
		dirs.append(os.path.realpath(os.path.join(xdg, "opencode")))
	return dirs


def _discovered_plugin_dirs(config_dir: str) -> list[str]:
	"""Dirs V2 auto-discovers plugins from.

	- Global ``<config>/plugins`` (and ``plugin``) for every global config dir.
	- ``.opencode/plugins`` and ``.opencode/plugin`` under the config dir and cwd.
	- ``<config_dir>/plugins`` ONLY when config_dir is a global opencode dir.
	Docs: a plugins/ dir beside a project-root opencode.json(c) is not discovered.
	"""
	dirs: list[str] = []
	for g in _global_config_dirs():
		dirs += [os.path.join(g, "plugins"), os.path.join(g, "plugin")]
	for root in (config_dir, os.getcwd()):
		dirs += [os.path.join(root, ".opencode", "plugins"), os.path.join(root, ".opencode", "plugin")]
	if os.path.realpath(config_dir) in _global_config_dirs():
		dirs += [os.path.join(config_dir, "plugins"), os.path.join(config_dir, "plugin")]
	return [os.path.realpath(d) for d in dirs]


def _single_file(path: str, config_dir: str) -> bool:
	if path.endswith((".js", ".ts", ".mjs", ".cjs")):
		return True
	candidate = path if os.path.isabs(path) else os.path.join(config_dir, path)
	return os.path.isfile(candidate)


def _normalize_plugin(entry, config_dir: str, discovered: list[str], report: list, warnings: list) -> list:
	"""Return a list of V2 plugin entries (usually 0 or 1)."""
	if isinstance(entry, dict):
		return [entry]

	path, opts = entry, None
	# tuple/list form: [path, options]
	if isinstance(entry, (list, tuple)):
		if not entry or not isinstance(entry[0], str):
			warnings.append(f"plugins: unrecognized tuple {entry!r}; dropped")
			return []
		path = entry[0]
		opts = entry[1] if len(entry) > 1 else None
	elif not isinstance(entry, str):
		warnings.append(f"plugins: unrecognized entry {entry!r}; dropped")
		return []

	if not _single_file(path, config_dir):
		if opts is not None:
			report.append(f"plugins: tuple -> object form for '{path}'")
			return [{"package": path, "options": opts}]
		return [path]

	resolved = path if os.path.isabs(path) else os.path.join(config_dir, path)
	resolved = os.path.normpath(resolved)
	parent = os.path.realpath(os.path.dirname(resolved))
	base = os.path.basename(resolved)
	stem = os.path.splitext(base)[0]

	if parent in discovered:
		if opts is not None:
			warnings.append(f"plugins: '{path}' options dropped (V2 auto-discovers the file)")
		report.append(f"plugins: dropped single-file '{path}' (V2 auto-discovers it from {parent})")
		return []

	if stem == "index":
		# index.js inside a plugin dir: configure the directory.
		report.append(f"plugins: '{path}' -> directory '{parent}' (V2 loads index/server)")
		return [{"package": parent, "options": opts}] if opts is not None else [parent]

	warnings.append(
		f"plugins: '{path}' is a single file outside any discovered plugins dir; V2 skips "
		f"configured file paths. Rename it to index.js inside its own directory and configure that directory."
	)
	return [{"package": path, "options": opts}] if opts is not None else [path]


# ── transforms ────────────────────────────────────────────────────────────────
def migrate_plugins(cfg: dict, config_dir: str, report: list, warnings: list) -> None:
	v1 = cfg.pop("plugin", None)
	existing = cfg.get("plugins")
	if v1 is None:
		if existing is not None:
			report.append("plugins: already V2 (present), left untouched")
		return
	if not isinstance(v1, list):
		v1 = [v1]
		warnings.append("plugin: expected a list; wrapped in one")

	discovered = _discovered_plugin_dirs(config_dir)
	converted: list = []
	for entry in v1:
		converted.extend(_normalize_plugin(entry, config_dir, discovered, report, warnings))

	merged = list(existing) if isinstance(existing, list) else []
	added = 0
	for e in converted:
		if e not in merged:
			merged.append(e)
			added += 1
	if merged:
		cfg["plugins"] = merged
	report.append(f"plugins: {len(v1)} V1 entr(y/ies) -> {added} added to plugins ({len(merged)} total)")


def _migrate_mcp_timeout(value):
	if isinstance(value, int) and not isinstance(value, bool):
		# V1 integer timeout -> V2 {catalog, execution} (migrate-v1#mcp-servers).
		return {"catalog": value, "execution": value}
	return value


def migrate_mcp(cfg: dict, report: list, warnings: list) -> None:
	mcp = cfg.get("mcp")
	if not isinstance(mcp, dict):
		return
	servers = mcp.get("servers") if isinstance(mcp.get("servers"), dict) else {}
	server_names = [k for k in mcp if k != "servers" and k != "timeout"]
	if "servers" in mcp and not server_names:
		report.append("mcp: already V2 (servers present)")
		return
	new_servers: dict = dict(servers)
	for name in server_names:
		srv = mcp[name]
		if not isinstance(srv, dict):
			warnings.append(f"mcp.{name}: expected object, got {type(srv).__name__}; skipped")
			continue
		ns = dict(srv)
		if "enabled" in ns:
			enabled = ns.pop("enabled")
			if enabled is False:
				ns["disabled"] = True
		if "timeout" in ns:
			ns["timeout"] = _migrate_mcp_timeout(ns["timeout"])
		new_servers[name] = ns
	new: dict = {}
	if "timeout" in mcp:
		converted = _migrate_mcp_timeout(mcp["timeout"])
		new["timeout"] = converted
		if converted is not mcp["timeout"]:
			warnings.append("mcp.timeout: integer -> {catalog, execution} (V2 startup not derivable)")
	new["servers"] = new_servers
	cfg["mcp"] = new
	report.append(f"mcp: {len(server_names)} server(s) under mcp.servers (enabled->disabled, timeout shape)")


def migrate_skills(cfg: dict, report: list, warnings: list) -> None:
	skills = cfg.get("skills")
	if skills is None or isinstance(skills, list):
		return
	if isinstance(skills, dict):
		out: list = []
		for key in ("paths", "urls"):
			val = skills.get(key)
			if isinstance(val, list):
				out.extend(val)
			elif isinstance(val, str):
				out.append(val)
		if out:
			cfg["skills"] = out
			report.append(f"skills: paths/urls -> array ({len(out)} entries)")
		else:
			warnings.append("skills: dict has no paths/urls; left untouched")
		extra = set(skills) - {"paths", "urls"}
		if extra:
			warnings.append(f"skills: dropped non-array keys {sorted(extra)} (V2 skills is an array)")
	else:
		warnings.append(f"skills: unrecognized shape {type(skills).__name__}; left untouched")


def _rules_from_mapping(action: str, value, warnings: list) -> list:
	v2_action = ACTION_ALIAS.get(action, action)
	rules: list = []
	if isinstance(value, dict):
		items = list(value.items())
		# V2 last-match-wins: the catch-all must come FIRST so specific rules win.
		items.sort(key=lambda kv: 0 if kv[0] == "*" else 1)
		for resource, effect in items:
			rules.append({"action": v2_action, "resource": resource, "effect": effect})
	elif isinstance(value, str):
		rules.append({"action": v2_action, "resource": "*", "effect": value})
	elif isinstance(value, bool):
		rules.append({"action": v2_action, "resource": "*", "effect": "allow" if value else "deny"})
	else:
		warnings.append(f"permission.{action}: unrecognized value {value!r}; skipped")
	return rules


_EFFECT_RANK = {"allow": 0, "ask": 1, "deny": 2}


def _coalesce_rules(rules: list, warnings: list) -> list:
	"""Merge duplicate (action, resource) rules, most restrictive effect wins.

	V2 is last-match-wins, so two rules for the same selector would make the
	outcome depend on source order (e.g. V1 ``write``+``edit`` both aliased to
	``edit``). Coalescing makes the result order-independent and conservative.
	"""
	order: list = []
	by_key: dict = {}
	for rule in rules:
		key = (rule.get("action"), rule.get("resource"))
		if key not in by_key:
			by_key[key] = rule
			order.append(key)
			continue
		prev = by_key[key]
		if prev.get("effect") != rule.get("effect"):
			warnings.append(
				f"permissions: conflicting effects for {key[0]} {key[1]!r} "
				f"({prev.get('effect')} vs {rule.get('effect')}); keeping the most restrictive"
			)
			if _EFFECT_RANK.get(rule.get("effect"), 0) > _EFFECT_RANK.get(prev.get("effect"), 0):
				by_key[key] = rule
	return [by_key[k] for k in order]


def migrate_permissions(cfg: dict, report: list, warnings: list) -> None:
	existing = cfg.get("permissions")
	perm = cfg.pop("permission", None)
	top_tools = cfg.pop("tools", None)

	rules: list = []
	groups = 0
	if isinstance(perm, dict):
		groups = len(perm)
		for action, value in perm.items():
			if action == "tools" and isinstance(value, dict):
				for tool, enabled in value.items():
					rules.append({"action": ACTION_ALIAS.get(tool, tool), "resource": "*", "effect": "allow" if enabled else "deny"})
				continue
			rules.extend(_rules_from_mapping(action, value, warnings))
	elif perm is not None:
		warnings.append(f"permission: expected object, got {type(perm).__name__}; ignored")
		if not isinstance(existing, list):
			cfg["permissions"] = perm
		else:
			warnings.append("permission: malformed V1 value ignored; existing permissions kept")

	if isinstance(top_tools, dict):
		for tool, enabled in top_tools.items():
			rules.append({"action": ACTION_ALIAS.get(tool, tool), "resource": "*", "effect": "allow" if enabled else "deny"})
		report.append(f"tools: {len(top_tools)} V1 tool flag(s) -> permission rules")

	if not rules:
		if existing is not None:
			report.append("permissions: already V2 (present), left untouched")
		return

	merged = _coalesce_rules(rules + (list(existing) if isinstance(existing, list) else []), warnings)
	cfg["permissions"] = merged
	report.append(f"permissions: {groups} V1 group(s) -> {len(rules)} rule(s); {len(merged)} total (coalesced, catch-all first, last-match-wins)")


def _migrate_model(model: dict, warnings: list) -> dict:
	out: dict = {}
	caps = dict(model.get("capabilities") or {})

	modalities = model.get("modalities")
	if isinstance(modalities, dict):
		if isinstance(modalities.get("input"), list):
			caps.setdefault("input", list(modalities["input"]))
		if isinstance(modalities.get("output"), list):
			caps.setdefault("output", list(modalities["output"]))
	if "tool_call" in model:
		caps.setdefault("tools", bool(model["tool_call"]))
	if "reasoning" in model:
		caps.setdefault("reasoning", {"supported": bool(model["reasoning"])})
	if isinstance(model.get("temperature"), bool):
		caps.setdefault("temperature", model["temperature"])
	elif "temperature" in model:
		warnings.append("model: numeric V1 'temperature' ignored (V2 capabilities.temperature is a support flag)")
	if "attachment" in model:
		inp = caps.get("input")
		if not inp:
			caps["input"] = ["text", "image"] if model["attachment"] else ["text"]
		elif model["attachment"] and "image" not in inp:
			caps["input"] = list(inp) + ["image"]

	if "id" in model and "modelID" not in model:
		out["modelID"] = model["id"]
	if "release_date" in model:
		out["releaseDate"] = model["release_date"]
	if isinstance(model.get("options"), dict) and "settings" not in model:
		out["settings"] = dict(model["options"])
	if model.get("status") == "deprecated":
		out["disabled"] = True

	for key in ("modelID", "name", "family", "releaseDate", "package", "settings", "headers", "body", "compatibility", "cost", "limit", "disabled"):
		if key in model:
			out[key] = model[key]

	cost = out.get("cost")
	if isinstance(cost, dict):
		cost = dict(cost)
		if "cache_read" in cost:
			cost["read"] = cost.pop("cache_read")
		if "cache_write" in cost:
			cost["write"] = cost.pop("cache_write")
		out["cost"] = cost

	if caps:
		out["capabilities"] = caps

	variants = model.get("variants")
	if isinstance(variants, dict):
		out["variants"] = [{"id": vid, **({"settings": v} if isinstance(v, dict) else {})} for vid, v in variants.items()]
	elif isinstance(variants, list):
		out["variants"] = variants

	for key, value in model.items():
		if key not in _MODEL_HANDLED and key not in out:
			out[key] = value
			warnings.append(f"model: unmapped V1 key '{key}' copied as-is (may be ignored by V2)")
	return out


def migrate_providers(cfg: dict, report: list, warnings: list) -> None:
	existing = cfg.get("providers")
	providers = cfg.pop("provider", None)
	if providers is None:
		if existing is not None:
			report.append("providers: already V2 (present), left untouched")
		return
	if not isinstance(providers, dict):
		warnings.append(f"provider: expected object, got {type(providers).__name__}; dropped")
		return

	out = dict(existing) if isinstance(existing, dict) else {}
	for pid, pcfg in providers.items():
		if not isinstance(pcfg, dict):
			warnings.append(f"provider.{pid}: expected object; skipped")
			continue
		np: dict = {}
		if "name" in pcfg:
			np["name"] = pcfg["name"]
		npm = pcfg.get("npm")
		if npm:
			if npm in NPM_PACKAGE_MAP:
				np["package"] = NPM_PACKAGE_MAP[npm]
				report.append(f"provider.{pid}: npm {npm} -> package {np['package']}")
			elif isinstance(npm, str) and npm.startswith("@ai-sdk/"):
				np["package"] = f"aisdk:{npm}"
				report.append(f"provider.{pid}: npm {npm} -> package {np['package']}")
			else:
				np["package"] = npm

		settings = dict(pcfg["options"]) if isinstance(pcfg.get("options"), dict) else {}
		cache_key = settings.pop("setCacheKey", None)
		if "api" in pcfg and "baseURL" not in settings:
			settings["baseURL"] = pcfg["api"]
		if settings:
			np["settings"] = settings
		compat = dict(pcfg["compatibility"]) if isinstance(pcfg.get("compatibility"), dict) else {}
		if cache_key is not None:
			compat["supportsPromptCacheKey"] = bool(cache_key)
		if compat:
			np["compatibility"] = compat
		for key in ("headers", "body", "env", "canonical"):
			if key in pcfg:
				np[key] = pcfg[key]
		models = pcfg.get("models")
		if isinstance(models, dict):
			np["models"] = {}
			for mid, model in models.items():
				if not isinstance(model, dict):
					warnings.append(f"provider.{pid}.models.{mid}: expected object; skipped")
					continue
				np["models"][mid] = _migrate_model(model, warnings)

		for key, value in pcfg.items():
			if key not in {"name", "npm", "options", "api", "headers", "body", "env", "canonical", "compatibility", "models"}:
				np.setdefault(key, value)
				warnings.append(f"provider.{pid}: unmapped V1 key '{key}' copied as-is (may be ignored by V2)")
		out[pid] = np
	cfg["providers"] = out
	report.append(f"providers: {len(providers)} provider(s) migrated (npm->package, api/options->settings, model shape)")


def migrate_default(cfg: dict, report: list, warnings: list) -> None:
	block = cfg.pop("default", None)
	if block is None:
		return
	if not isinstance(block, dict):
		warnings.append(f"default: unexpected {type(block).__name__}; dropped")
		return
	model = block.get("model")
	provider = block.get("provider")
	if model and provider and "/" not in str(model):
		model = f"{provider}/{model}"
	if model and not cfg.get("model"):
		cfg["model"] = model
	extra = sorted(set(block) - {"provider", "model"})
	if extra:
		warnings.append(f"default: dropped keys {extra} (V2 has no default block)")
	report.append(f"default: block removed; model={cfg.get('model')!r}")


def migrate_provider_lists(cfg: dict, report: list, warnings: list) -> None:
	disabled = cfg.get("disabled_providers")
	enabled = cfg.get("enabled_providers")
	if not disabled and not enabled:
		cfg.pop("disabled_providers", None)
		cfg.pop("enabled_providers", None)
		return
	policies = cfg.get("policies", [])
	if not isinstance(policies, list):
		warnings.append("policies: expected array; cannot append provider lists (left untouched)")
		return
	cfg.pop("disabled_providers", None)
	cfg.pop("enabled_providers", None)
	if disabled:
		for pid in disabled:
			policies.append({"action": "provider.use", "resource": pid, "effect": "deny"})
		report.append(f"disabled_providers -> policies: {len(disabled)} deny rule(s)")
	if enabled:
		policies.append({"action": "provider.use", "resource": "*", "effect": "deny"})
		for pid in enabled:
			policies.append({"action": "provider.use", "resource": pid, "effect": "allow"})
		report.append(f"enabled_providers -> policies: deny * + {len(enabled)} allow rule(s)")
	cfg["policies"] = policies


def migrate_experimental(cfg: dict, report: list, warnings: list) -> None:
	exp = cfg.get("experimental")
	if not isinstance(exp, dict) or "mcp_timeout" not in exp:
		return
	value = exp.pop("mcp_timeout")
	mcp = cfg.setdefault("mcp", {})
	if not isinstance(mcp, dict):
		warnings.append("experimental.mcp_timeout: mcp is not an object; left in experimental")
		exp["mcp_timeout"] = value
		return
	if "timeout" in mcp:
		warnings.append("experimental.mcp_timeout ignored: mcp.timeout already set")
	else:
		mcp["timeout"] = _migrate_mcp_timeout(value)
		report.append(f"experimental.mcp_timeout -> mcp.timeout ({value})")
	if not exp:
		cfg.pop("experimental", None)


# ── driver ────────────────────────────────────────────────────────────────────
def _needs_migration(cfg: dict) -> bool:
	if any(k in cfg for k in V1_KEYS):
		return True
	if isinstance(cfg.get("tools"), dict):
		return True
	if isinstance(cfg.get("experimental"), dict) and "mcp_timeout" in cfg["experimental"]:
		return True
	skills = cfg.get("skills")
	if isinstance(skills, dict) and ("paths" in skills or "urls" in skills):
		return True
	mcp = cfg.get("mcp")
	if isinstance(mcp, dict) and any(k not in ("timeout", "servers") for k in mcp):
		return True
	return False


def migrate(cfg: dict, config_dir: str) -> tuple[dict, list, list]:
	report: list = []
	warnings: list = []
	migrate_plugins(cfg, config_dir, report, warnings)
	migrate_mcp(cfg, report, warnings)
	migrate_experimental(cfg, report, warnings)
	migrate_skills(cfg, report, warnings)
	migrate_permissions(cfg, report, warnings)
	migrate_providers(cfg, report, warnings)
	migrate_default(cfg, report, warnings)
	migrate_provider_lists(cfg, report, warnings)
	return cfg, report, warnings


def main() -> int:
	parser = argparse.ArgumentParser(description="Migrate opencode.jsonc from V1 to V2.")
	parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"Source opencode.jsonc (default {DEFAULT_CONFIG}).")
	parser.add_argument("--output", default=None, help="Destination (default: --config, in place).")
	parser.add_argument("--dry-run", action="store_true", help="Print the plan and write nothing.")
	parser.add_argument("--no-backup", action="store_true", help="Do not write a .v1.bak before overwriting.")
	parser.add_argument("--force", action="store_true", help="Re-run even if no V1 keys are present.")
	parser.add_argument("-v", "--verbose", action="store_true")
	args = parser.parse_args()

	logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")

	config_path = os.path.expanduser(args.config)
	if not os.path.isfile(config_path):
		logger.error("Config not found: %s", config_path)
		return 2

	config_dir = os.path.dirname(os.path.realpath(config_path))
	raw = open(config_path, "r", encoding="utf-8").read()
	cfg = load_jsonc(config_path)

	if not _needs_migration(cfg) and not args.force:
		logger.info("Nothing to do: %s has no V1 keys left.", config_path)
		return 0

	migrated, report, warnings = migrate(cfg, config_dir)

	print("── Migration report " + "─" * 40)
	for line in report:
		print(f"  • {line}")
	if warnings:
		print("── Warnings (manual review) " + "─" * 32)
		for line in warnings:
			print(f"  ! {line}")
	print("─" * 59)

	if args.dry_run:
		print("\n[dry-run] output would be:\n")
		print(json.dumps(migrated, indent=2, ensure_ascii=False))
		return 0

	output_path = os.path.expanduser(args.output) if args.output else config_path
	if not args.no_backup and os.path.realpath(output_path) == os.path.realpath(config_path) and os.path.exists(config_path):
		stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
		backup = f"{config_path}.v1.bak.{stamp}"
		while os.path.exists(backup):
			backup += ".1"
		shutil.copy2(config_path, backup)
		logger.info("Backup: %s", backup)

	parent = os.path.dirname(os.path.abspath(output_path))
	if parent:
		os.makedirs(parent, exist_ok=True)
	with open(output_path, "w", encoding="utf-8") as fh:
		json.dump(migrated, fh, indent=2, ensure_ascii=False)
		fh.write("\n")
	logger.info("Wrote V2 config: %s", output_path)
	if _strip_comments(raw) != raw:
		logger.warning("Original had JSONC comments; the written V2 file is plain JSON (backup keeps them).")
	return 0


if __name__ == "__main__":
	sys.exit(main())
