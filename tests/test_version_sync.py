import re
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent


def get_version_from_pyproject():
	pyproject = (ROOT_DIR / "pyproject.toml").read_text()
	match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
	return match.group(1) if match else None


def test_version_consistency():
	"""Ensures version is synchronized across all critical files (Strict Header Check)."""
	version = get_version_from_pyproject()
	assert version is not None, "Version not found in pyproject.toml"

	# 1. Check src/red_pill/__init__.py
	init_file = (ROOT_DIR / "src" / "red_pill" / "__init__.py").read_text()
	assert f'__version__ = "{version}"' in init_file

	# 2. Check README.md (Header line 1)
	readme_line1 = (ROOT_DIR / "README.md").read_text().splitlines()[0]
	assert f"v{version}" in readme_line1, f"README header mismatch: {readme_line1} (expected v{version})"

	# 3. Check docs/TECHNICAL/ARCHITECTURE.md (Regex for version)
	arch_content = (ROOT_DIR / "docs" / "TECHNICAL" / "ARCHITECTURE.md").read_text()
	arch_match = re.search(r"\*\*System Version\*\*:\s*v([^\s\)]+)", arch_content)
	assert arch_match is not None, "Version string not found in ARCHITECTURE.md"
	assert arch_match.group(1) == version, f"Architecture version mismatch: {arch_match.group(1)} (expected {version})"

	# 4. Check .env.example (Header line 1)
	env_example_line1 = (ROOT_DIR / ".env.example").read_text().splitlines()[0]
	assert f"v{version}" in env_example_line1, f".env.example header mismatch: {env_example_line1}"

	# 5. Check CHANGELOG.md (should be the latest entry)
	changelog = (ROOT_DIR / "CHANGELOG.md").read_text()
	assert f"## [{version}]" in changelog


def test_changelog_is_latest():
	"""Ensures the version in pyproject is the most recent entry in CHANGELOG.md."""
	version = get_version_from_pyproject()
	changelog = (ROOT_DIR / "CHANGELOG.md").read_text()

	# Find the first entry header like ## [X.Y.Z]
	match = re.search(r"## \[([^\]]+)\]", changelog)
	assert match is not None, "No version entries found in CHANGELOG.md"
	assert match.group(1) == version, f"CHANGELOG.md latest version ({match.group(1)}) does not match pyproject.toml ({version})"


def test_python_runtime_sync():
	"""Ensures the Python version in CI matches the Dockerfile target."""
	ci_content = (ROOT_DIR / ".github" / "workflows" / "ci.yml").read_text()
	docker_content = (ROOT_DIR / "tests" / "Dockerfile.keymaker").read_text()

	# Find the list of versions in the matrix
	ci_match = re.search(r"python-version:\s*\[([^\]]+)\]", ci_content)
	if not ci_match:
		# Fallback to single version check
		ci_match = re.search(r'python-version:\s*"([^"]+)"', ci_content)
		assert ci_match is not None, "python-version not found in ci.yml"
		ci_python_version = ci_match.group(1)
	else:
		# Get the last version in the list (most modern)
		versions = [v.strip().strip('"').strip("'") for v in ci_match.group(1).split(",")]
		ci_python_version = versions[-1]

	docker_match = re.search(r"^FROM\s+python:([^\s-]+)", docker_content, re.M)
	assert docker_match is not None, "python base image not found in Dockerfile"
	docker_python_version = docker_match.group(1)

	assert ci_python_version == docker_python_version, (
		f"Python runtime mismatch! CI (latest): {ci_python_version} vs Dockerfile: {docker_python_version}"
	)
