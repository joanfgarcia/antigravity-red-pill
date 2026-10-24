#!/usr/bin/env python3
"""Render the active GIT_WORKFLOW profile for a scaffolded project (stdlib only)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PROFILES = ("solo", "canonical")
_BLOCK_RE = re.compile(r"<!--\s*profile:(solo|canonical):start\s*-->(.*?)<!--\s*profile:(solo|canonical):end\s*-->", re.DOTALL)
_MARKER_RE = re.compile(r"<!--\s*profile:(solo|canonical):(start|end)\s*-->")


def render(profile: str, source: str) -> str:
	name = profile.strip().lower()
	if name not in PROFILES:
		raise ValueError(f"GIT_WORKFLOW inválido: {profile!r}")
	if any(f"profile:{candidate}:start" not in source for candidate in PROFILES):
		raise ValueError("git_workflow template sin bloques solo/canonical")
	out = _BLOCK_RE.sub(lambda m: m.group(2) if m.group(1) == name else "", source)
	out = _MARKER_RE.sub("", out).replace("{{profile}}", name)
	return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--profile", default="solo")
	parser.add_argument("--source", required=True)
	parser.add_argument("--output", required=True)
	args = parser.parse_args()
	source = Path(args.source).read_text(encoding="utf-8")
	dest = Path(args.output)
	dest.parent.mkdir(parents=True, exist_ok=True)
	dest.write_text(render(args.profile, source), encoding="utf-8")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
