import re
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent


def get_version_from_pyproject():
	pyproject = (ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8")
	match = re.search('^version\\s*=\\s*"([^"]+)"', pyproject, re.M)
	return match.group(1) if match else None


def test_version_consistency():
	"""Ensures version is synchronized across all critical files (Strict Header Check)."""
	version = get_version_from_pyproject()
	assert version is not None, "Version not found in pyproject.toml"
	init_file = (ROOT_DIR / "src" / "red_pill" / "__init__.py").read_text(encoding="utf-8")
	assert f'__version__ = "{version}"' in init_file
	readme_line1 = (ROOT_DIR / "README.md").read_text(encoding="utf-8").splitlines()[0]
	assert f"v{version}" in readme_line1, f"README header mismatch: {readme_line1} (expected v{version})"
	arch_content = (ROOT_DIR / "docs" / "TECHNICAL" / "ARCHITECTURE.md").read_text(encoding="utf-8")
	arch_match = re.search("\\*\\*System Version\\*\\*:\\s*v([^\\s\\)]+)", arch_content)
	assert arch_match is not None, "Version string not found in ARCHITECTURE.md"
	assert arch_match.group(1) == version, f"Architecture version mismatch: {arch_match.group(1)} (expected {version})"
	env_example_line1 = (ROOT_DIR / ".env.example").read_text(encoding="utf-8").splitlines()[0]
	assert f"v{version}" in env_example_line1, f".env.example header mismatch: {env_example_line1}"
	changelog = (ROOT_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
	assert f"## [{version}]" in changelog
	security_content = (ROOT_DIR / "SECURITY.md").read_text(encoding="utf-8")
	# CF-003: Ensure SECURITY.md mentions at least the major.minor family
	major_minor = ".".join(version.split(".")[:2])
	assert f"{major_minor}.x" in security_content, f"Version family {major_minor}.x not supported in SECURITY.md"


def test_changelog_is_latest():
	"""Ensures the version in pyproject is the most recent entry in CHANGELOG.md."""
	version = get_version_from_pyproject()
	changelog = (ROOT_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
	match = re.search("## \\[([^\\]]+)\\]", changelog)
	assert match is not None, "No version entries found in CHANGELOG.md"
	assert match.group(1) == version, f"CHANGELOG.md latest version ({match.group(1)}) does not match pyproject.toml ({version})"


def test_python_runtime_sync():
	"""Ensures the Python version in CI matches the Dockerfile target."""
	ci_content = (ROOT_DIR / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
	docker_content = (ROOT_DIR / "docker" / "Dockerfile.keymaker").read_text(encoding="utf-8")
	ci_match = re.search("python-version:\\s*\\[([^\\]]+)\\]", ci_content)
	if not ci_match:
		ci_match = re.search('python-version:\\s*"([^"]+)"', ci_content)
		assert ci_match is not None, "python-version not found in ci.yml"
		ci_python_version = ci_match.group(1)
	else:
		versions = [v.strip().strip('"').strip("'") for v in ci_match.group(1).split(",")]
		ci_python_version = versions[-1]
	docker_match = re.search("^FROM\\s+python:([^\\s-]+)", docker_content, re.M)
	assert docker_match is not None, "python base image not found in Dockerfile"
	docker_python_version = docker_match.group(1)
	assert ci_python_version == docker_python_version, (
		f"Python runtime mismatch! CI (latest): {ci_python_version} vs Dockerfile: {docker_python_version}"
	)
