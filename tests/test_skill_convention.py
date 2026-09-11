"""Convención de skills (Agent Skills standard): dir == name, kebab-case.

Guarda la regresión del rename 2026-09-10 (snake_case → kebab-case): opencode
lo enforcea, Pi avisa con warnings. Un skill del repo debe satisfacer:
- directorio == frontmatter `name`
- kebab-case (a-z, 0-9, guiones; sin líder/final/dobles), 1-64 chars
- `description` no vacía y <= 1024 chars
"""

from __future__ import annotations

import os
import re

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _skill_dirs():
	dirs = [os.path.join(REPO_ROOT, "skills"), os.path.join(REPO_ROOT, "seeds", "opencode", "skills")]
	for ide in ("pi", "claude-code", "antigravity", "gemini"):
		dirs.append(os.path.join(REPO_ROOT, "seeds", ide, "skills"))
	seen = set()
	out = []
	for base in dirs:
		if not os.path.isdir(base):
			continue
		for entry in sorted(os.listdir(base)):
			skill_md = os.path.join(base, entry, "SKILL.md")
			if os.path.isdir(os.path.join(base, entry)) and os.path.exists(skill_md):
				if skill_md not in seen:
					seen.add(skill_md)
					out.append((entry, skill_md))
	return out


def _frontmatter(path: str) -> dict:
	with open(path, encoding="utf-8") as f:
		text = f.read()
	if not text.startswith("---"):
		return {}
	m = re.search(r"^---\n(.*?)\n---", text, re.S)
	if not m:
		return {}
	meta = {}
	for line in m.group(1).splitlines():
		if ":" in line and not line.lstrip().startswith("#"):
			key, _, val = line.partition(":")
			meta[key.strip()] = val.strip()
	return meta


@pytest.mark.parametrize("entry,md_path", _skill_dirs())
def test_skill_dir_matches_frontmatter_and_is_kebab(entry, md_path):
	meta = _frontmatter(md_path)
	name = meta.get("name", "")
	assert name, f"{md_path}: frontmatter sin `name`"
	# 1. Directorio == frontmatter name
	assert name == entry, f"{md_path}: dir '{entry}' != name '{name}'"
	# 2. kebab-case
	assert KEBAB.match(name) and len(name) <= 64, f"{md_path}: name '{name}' no es kebab-case válido (1-64, a-z0-9 y guiones simples)"
	# 3. Descripción obligatoria
	desc = meta.get("description", "")
	assert desc, f"{md_path}: frontmatter sin `description`"
	assert len(desc) <= 1024, f"{md_path}: description > 1024 chars"


def test_no_snake_case_skill_dirs_remain():
	"""Los directorios de skills del repo no pueden ser snake_case."""
	bad = []
	for entry, _md in _skill_dirs():
		if "_" in entry:
			bad.append(entry)
	assert not bad, f"skills snake_case encontrados: {bad}"
