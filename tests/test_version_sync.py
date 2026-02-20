import re
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent

def get_version_from_pyproject():
	pyproject = (ROOT_DIR / "pyproject.toml").read_text()
	match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
	return match.group(1) if match else None

def test_version_consistency():
	"""Ensures version is synchronized across all critical files."""
	version = get_version_from_pyproject()
	assert version is not None, "Version not found in pyproject.toml"

	# 1. Check src/red_pill/__init__.py
	init_file = (ROOT_DIR / "src" / "red_pill" / "__init__.py").read_text()
	assert f'__version__ = "{version}"' in init_file

	# 2. Check README.md
	readme = (ROOT_DIR / "README.md").read_text()
	assert f"v{version}" in readme

	# 3. Check docs/technical/ARCHITECTURE.md
	arch_file = (ROOT_DIR / "docs" / "technical" / "ARCHITECTURE.md").read_text()
	assert f"v{version}" in arch_file

	# 4. Check CHANGELOG.md (should be the latest entry)
	changelog = (ROOT_DIR / "CHANGELOG.md").read_text()
	assert f"## [{version}]" in changelog

def test_changelog_is_latest():
	"""Ensures the version in pyproject is the most recent entry in CHANGELOG.md."""
	version = get_version_from_pyproject()
	changelog = (ROOT_DIR / "CHANGELOG.md").read_text()
	
	# Find the first entry header like ## [X.Y.Z]
	match = re.search(r'## \[([^\]]+)\]', changelog)
	assert match is not None, "No version entries found in CHANGELOG.md"
	assert match.group(1) == version, f"CHANGELOG.md latest version ({match.group(1)}) does not match pyproject.toml ({version})"
