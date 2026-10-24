"""Render the profile-specific Git workflow rule.

`seeds/rules/git_workflow.md` is a template with common invariants and two
profile blocks. The installer/`bunker update` renders **only** the active
`GIT_WORKFLOW` profile to `~/.agent/rules/git_workflow.md`; the agent never
chooses between both at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path

PROFILES = ("solo", "canonical")
_BLOCK_RE = re.compile(r"<!--\s*profile:(solo|canonical):start\s*-->(.*?)<!--\s*profile:(solo|canonical):end\s*-->", re.DOTALL)
_MARKER_RE = re.compile(r"<!--\s*profile:(solo|canonical):(start|end)\s*-->")


class GitWorkflowError(ValueError):
	"""The workflow seed is missing a profile block or the profile is invalid."""


def render_git_workflow(profile: str, source: str) -> str:
	"""Return the rule text for one profile (no inactive profile, no markers)."""
	name = str(profile or "").strip().lower()
	if name not in PROFILES:
		raise GitWorkflowError(f"GIT_WORKFLOW inválido: {profile!r} (esperado solo|canonical)")
	found = {match.group(1) for match in _BLOCK_RE.finditer(source)}
	missing = [candidate for candidate in PROFILES if candidate not in found]
	if missing:
		raise GitWorkflowError(f"seed sin bloque(s) de perfil: {missing!r}")

	def _replace(match: re.Match[str]) -> str:
		candidate = match.group(1)
		return match.group(2) if candidate == name else ""

	out = _BLOCK_RE.sub(_replace, source)
	out = _MARKER_RE.sub("", out)
	out = out.replace("{{profile}}", name)
	out = re.sub(r"\n{3,}", "\n\n", out)
	return out.strip() + "\n"


def write_git_workflow(profile: str, source_path: Path, dest_path: Path) -> str:
	"""Render `source_path` for `profile` and write the deployed rule atomically."""
	source = Path(source_path).read_text(encoding="utf-8")
	rendered = render_git_workflow(profile, source)
	dest = Path(dest_path)
	dest.parent.mkdir(parents=True, exist_ok=True)
	tmp = dest.with_name(f".{dest.name}.tmp")
	tmp.write_text(rendered, encoding="utf-8")
	tmp.replace(dest)
	return rendered
