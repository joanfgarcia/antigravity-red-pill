#!/usr/bin/env python3
"""Harness boot-cost meter — RFC-HARNESS-001 · P0 / W0.

What it measures (what the model pays *before* the first token):

1. **Anchors** — every `<!-- REDPILL:BEGIN … -->` block spliced into the harness'
	instruction file, block by block.
2. **Skills catalogue** — only `name` + `description` from each `SKILL.md`
	frontmatter (that is all a harness advertises until the skill is loaded).
3. **MCP surface** — the tools the kernel *declares* (`registry.get_tools()`),
	with the JSON schema actually serialised, so the number is not a guess.

Tokens are measured with a real tokenizer and the instrument is printed. Nothing
here reports "tokens" without saying which tokenizer produced them; if none is
available the figure is labelled ESTIMATE with the ratio used (audit S01/S30:
a gate that cannot fail is not a gate).

Usage::

		PYTHONPATH=src .venv/bin/python scripts/harness_cost.py
		PYTHONPATH=src .venv/bin/python scripts/harness_cost.py --json
		PYTHONPATH=src .venv/bin/python scripts/harness_cost.py --profile gateway
		PYTHONPATH=src .venv/bin/python scripts/harness_cost.py --workspace ~/Documents/IA/sharing

Exit codes: 0 ok · 3 the MCP registry could not be read (never report 0 silently).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.core.paths import get_models_dir

BLOCK_RE = re.compile(r"<!-- REDPILL:BEGIN (\w+) v=(\d+) -->(.*?)<!-- REDPILL:END \1 -->", re.S)
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.S)
ESTIMATE_RATIO = 3.7  # chars/token fallback; measured on this corpus with Qwen3

# El tokenizer de Qwen3 vive en la raíz de modelos del kernel; el cache de HF es
# de terceros (se prueba como respaldo). Las rutas de los arneses (`.opencode`,
# `.claude`, `.pi`) son de terceros por convención y NO existen en `core/paths.py`.
TOKENIZER_CANDIDATES = [
	str(get_models_dir() / "Qwen3-1.7B" / "tokenizer.json"),
	str(Path.home() / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3-1.7B" / "snapshots"),
]

ANCHOR_FILES = {
	"opencode": ["~/.config/opencode/AGENTS.md"],
	"claude-code": ["~/.claude/CLAUDE.md"],
	"claude-desktop": ["~/.claude/CLAUDE.md"],
	"pi": ["{workspace}/AGENTS.override.md", "{workspace}/AGENTS.md"],
}

SKILL_ROOTS = {
	"opencode": "~/.config/opencode/skills",
	"pi": "~/.pi/agent/skills",
}

# Tools that a harness keeps *declared at boot* under each surface profile.
# `gateway` = the P1b design: only what is hot, everything else behind
# redpill_search/redpill_call (which are themselves declared, so they are
# costed as small placeholders until they exist — labelled as estimates).
GATEWAY_HOT = ("bunker_memory_api",)
GATEWAY_PLACEHOLDER_BYTES = 420  # redpill_search + redpill_call, ~estimate


# ── instruments ──────────────────────────────────────────────────────────────


def _expand(path: str, workspace: Optional[str]) -> Path:
	return Path(os.path.expandvars(os.path.expanduser(path.format(workspace=workspace or "~"))))


def load_tokenizer() -> Tuple[Optional[Any], str]:
	"""Return (tokenizer, instrument_name). Fallback: (None, 'ESTIMATE')."""
	try:
		from tokenizers import Tokenizer  # type: ignore
	except Exception:
		return None, "ESTIMATE(chars/3.7)"
	for candidate in TOKENIZER_CANDIDATES:
		path = Path(os.path.expanduser(candidate))
		files: List[Path] = []
		if path.is_file():
			files = [path]
		elif path.is_dir():
			files = sorted(path.rglob("tokenizer.json"))
		for f in files:
			try:
				tok = Tokenizer.from_file(str(f))
				return tok, f"tokenizers:{f}"
			except Exception:
				continue
	return None, "ESTIMATE(chars/3.7)"


def count_tokens(text: str, tok: Optional[Any]) -> int:
	if not text:
		return 0
	if tok is not None:
		try:
			return len(tok.encode(text).ids)
		except Exception:
			pass
	return int(round(len(text) / ESTIMATE_RATIO))


# ── measurements ─────────────────────────────────────────────────────────────


@dataclass
class Block:
	name: str
	version: str
	chars: int
	tokens: int


@dataclass
class AnchorReport:
	path: str
	exists: bool
	bytes: int = 0
	tokens: int = 0
	blocks: List[Block] = field(default_factory=list)
	unmanaged_bytes: int = 0


def measure_anchor(path: Path, tok: Optional[Any]) -> AnchorReport:
	report = AnchorReport(path=str(path), exists=path.is_file())
	if not report.exists:
		return report
	text = path.read_text(encoding="utf-8")
	report.bytes = len(text.encode())
	report.tokens = count_tokens(text, tok)
	managed = 0
	for m in BLOCK_RE.finditer(text):
		name, version, body = m.group(1), m.group(2), m.group(3)
		managed += len(m.group(0).encode())
		report.blocks.append(Block(name=name, version=version, chars=len(body), tokens=count_tokens(body, tok)))
	report.unmanaged_bytes = max(0, report.bytes - managed)
	return report


@dataclass
class SkillReport:
	root: str
	exists: bool
	count: int = 0
	chars: int = 0
	tokens: int = 0
	per_skill: List[Tuple[str, int]] = field(default_factory=list)


def _frontmatter(path: Path) -> Dict[str, str]:
	try:
		text = path.read_text(encoding="utf-8")
	except OSError:
		return {}
	m = FRONTMATTER_RE.match(text)
	if not m:
		return {}
	raw = m.group(1)
	out: Dict[str, str] = {}
	try:
		import yaml  # type: ignore

		data = yaml.safe_load(raw) or {}
		if isinstance(data, dict):
			for key in ("name", "description"):
				if key in data and data[key] is not None:
					out[key] = str(data[key])
			if out:
				return out
	except Exception:
		pass
	for key in ("name", "description"):
		km = re.search(rf"^{key}:\s*(.+)$", raw, re.M)
		if km:
			out[key] = km.group(1).strip().strip("\"'")
	return out


def measure_skills(root: Path, tok: Optional[Any]) -> SkillReport:
	report = SkillReport(root=str(root), exists=root.is_dir())
	if not report.exists:
		return report
	for skill_md in sorted(root.glob("*/SKILL.md")):
		fm = _frontmatter(skill_md)
		text = f"{fm.get('name', skill_md.parent.name)} {fm.get('description', '')}".strip()
		report.count += 1
		n = count_tokens(text, tok)
		report.chars += len(text)
		report.tokens += n
		report.per_skill.append((skill_md.parent.name, n))
	report.per_skill.sort(key=lambda item: item[1], reverse=True)
	return report


@dataclass
class ToolReport:
	name: str
	bytes: int
	tokens: int


def measure_tools(tok: Optional[Any]) -> List[ToolReport]:
	"""Import the kernel registry and serialise every declared tool."""
	import red_pill.mcp_server  # noqa: F401 — populates the registry
	from red_pill.registry import registry

	out: List[ToolReport] = []
	for tool in registry.get_tools():
		payload = json.dumps(tool.model_dump(by_alias=True), ensure_ascii=False)
		out.append(ToolReport(name=tool.name, bytes=len(payload.encode()), tokens=count_tokens(payload, tok)))
	out.sort(key=lambda item: item.bytes, reverse=True)
	return out


# ── reporting ────────────────────────────────────────────────────────────────


def _fmt_tokens(n: int, instrument: str) -> str:
	return f"{n:,} tok" if not instrument.startswith("ESTIMATE") else f"{n:,} tok*"


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
	tok, instrument = load_tokenizer()
	harnesses: Dict[str, Any] = {}

	for harness, patterns in ANCHOR_FILES.items():
		if args.harness not in ("all", harness):
			continue
		anchors = [measure_anchor(_expand(pattern, args.workspace), tok) for pattern in patterns]
		anchors = [a for a in anchors if a.exists] or anchors[:1]
		skills = measure_skills(_expand(SKILL_ROOTS[harness], args.workspace), tok) if harness in SKILL_ROOTS else SkillReport(root="", exists=False)
		harnesses[harness] = {
			"anchors": [a.__dict__ | {"blocks": [b.__dict__ for b in a.blocks]} for a in anchors],
			"skills": skills.__dict__,
		}

	tools = measure_tools(tok)
	if args.profile == "full":
		declared = tools
	elif args.profile == "gateway":
		declared = [t for t in tools if t.name in GATEWAY_HOT]
	elif args.profile == "none":
		declared = []
	else:  # pragma: no cover - argparse restricts this
		raise SystemExit(f"unknown profile {args.profile}")

	declared_bytes = sum(t.bytes for t in declared)
	declared_tokens = sum(t.tokens for t in declared)
	if args.profile == "gateway":
		# search/call are not implemented yet (P1b): costed as a labelled estimate.
		declared_bytes += GATEWAY_PLACEHOLDER_BYTES
		declared_tokens += count_tokens("x" * GATEWAY_PLACEHOLDER_BYTES, tok)

	for harness, data in harnesses.items():
		anchor_tokens = sum(a["tokens"] for a in data["anchors"])
		data["totals"] = {
			"anchors_tokens": anchor_tokens,
			"skills_tokens": data["skills"]["tokens"],
			"tools_tokens": declared_tokens,
			"boot_tokens": anchor_tokens + data["skills"]["tokens"] + declared_tokens,
		}

	return {
		"instrument": instrument,
		"profile": args.profile,
		"declared_tools": len(declared),
		"declared_tools_bytes": declared_bytes,
		"declared_tools_tokens": declared_tokens,
		"all_tools": [t.__dict__ for t in tools],
		"declared": [t.__dict__ for t in declared],
		"harnesses": harnesses,
	}


def render_markdown(report: Dict[str, Any]) -> str:
	instrument = report["instrument"]
	estimated = instrument.startswith("ESTIMATE")
	lines: List[str] = []
	lines.append("# Harness boot cost")
	lines.append("")
	lines.append(f"- **Instrumento**: `{instrument}`" + ("  ← todos los tokens son ESTIMADOS" if estimated else ""))
	lines.append(f"- **Perfil de superficie**: `{report['profile']}`")
	lines.append(
		f"- **Tools declaradas**: {report['declared_tools']} · {report['declared_tools_bytes']:,} B · {_fmt_tokens(report['declared_tools_tokens'], instrument)}"
	)
	lines.append("")
	lines.append("> Alcance: esto es lo que el **servidor** puede declarar. Lo que cada cliente")
	lines.append("> declara al arrancar es un subconjunto (Code Mode renderiza un catálogo parcial),")
	lines.append("> así que estas cifras son **cota superior** salvo donde el cliente declare todo.")
	lines.append("> Cerrar esa diferencia requiere capturar el system prompt real de una sesión (P0).")
	lines.append("")

	for harness, data in report["harnesses"].items():
		lines.append(f"## {harness}")
		lines.append("")
		lines.append("| Componente | Bytes | Tokens |")
		lines.append("|---|---:|---:|")
		for anchor in data["anchors"]:
			if not anchor["exists"]:
				lines.append(f"| anchor `{anchor['path']}` | — | (no existe) |")
				continue
			lines.append(f"| anchor (total) `{anchor['path']}` | {anchor['bytes']:,} | {_fmt_tokens(anchor['tokens'], instrument)} |")
			for block in anchor["blocks"]:
				lines.append(f"| ↳ `{block['name']}` v{block['version']} | — | {_fmt_tokens(block['tokens'], instrument)} |")
			if anchor["unmanaged_bytes"]:
				lines.append(f"| ↳ fuera de bloques | {anchor['unmanaged_bytes']:,} | — |")
		skills = data["skills"]
		if skills["exists"]:
			lines.append(f"| skills ({skills['count']}) | {skills['chars']:,} chars | {_fmt_tokens(skills['tokens'], instrument)} |")
		else:
			lines.append("| skills | — | (no hay directorio) |")
		lines.append(
			f"| tools declaradas ({report['declared_tools']}) | {report['declared_tools_bytes']:,} | {_fmt_tokens(report['declared_tools_tokens'], instrument)} |"
		)
		lines.append(f"| **arranque** | | **{_fmt_tokens(data['totals']['boot_tokens'], instrument)}** |")
		lines.append("")

	lines.append("## Tools declaradas (todas)")
	lines.append("")
	lines.append("| Tool | Bytes | Tokens |")
	lines.append("|---|---:|---:|")
	for tool in report["all_tools"]:
		lines.append(f"| `{tool['name']}` | {tool['bytes']:,} | {_fmt_tokens(tool['tokens'], instrument)} |")
	lines.append("")
	if report["profile"] == "gateway":
		lines.append(f"> `gateway` incluye {GATEWAY_PLACEHOLDER_BYTES} B de marcador para `redpill_search`/`redpill_call` (aún no existen).")
		lines.append("")
	if estimated:
		lines.append("> `*` = estimación con chars/3.7, no medida. Instalar un tokenizer para tener cifras reales.")
		lines.append("")
	return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="Harness boot-cost meter (RFC-HARNESS-001)")
	parser.add_argument("--harness", default="all", choices=["all", *ANCHOR_FILES.keys()])
	parser.add_argument("--profile", default="full", choices=["full", "gateway", "none"])
	parser.add_argument("--workspace", default=None, help="workspace root for workspace-scoped anchors (pi)")
	parser.add_argument("--json", action="store_true", help="machine-readable output")
	parser.add_argument("--out", default=None, help="write the markdown report to this path")
	args = parser.parse_args(argv)

	try:
		report = build_report(args)
	except Exception as exc:  # noqa: BLE001 — never report a silent zero
		print(f"[harness_cost] no se pudo medir la superficie MCP: {exc}", file=sys.stderr)
		return 3

	if args.json:
		print(json.dumps(report, ensure_ascii=False, indent=2))
	else:
		markdown = render_markdown(report)
		if args.out:
			Path(os.path.expanduser(args.out)).write_text(markdown + "\n", encoding="utf-8")
			print(f"[harness_cost] escrito en {args.out}")
		else:
			print(markdown)
	return 0


if __name__ == "__main__":
	sys.exit(main())
