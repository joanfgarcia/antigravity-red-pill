from pathlib import Path


def test_no_legacy_storage_paths():
	"""
	Smith Filter: Ensures that no Python file in src/ directly references
	the legacy 'storage' directory. XDG paths (from paths.py) must be used.
	"""
	src_dir = Path(__file__).parent.parent / "src"

	banned_substrings = [
		'"storage"',
		"'storage'",
		'"storage/',
		"'storage/",
		'os.path.join(APP_ROOT, "storage")',
		'os.path.join(PROJECT_ROOT, "storage")',
	]

	violations = []

	for py_file in src_dir.rglob("*.py"):
		try:
			with open(py_file, "r", encoding="utf-8") as f:
				lines = f.readlines()
			for i, line in enumerate(lines):
				if any(banned in line for banned in banned_substrings):
					# Ignorar comentarios si es necesario
					if not line.strip().startswith("#"):
						violations.append(f"{py_file.relative_to(src_dir.parent)}:{i + 1} -> {line.strip()}")
		except Exception:
			pass

	assert not violations, "XDG Compliance violation (legacy 'storage' used):\n" + "\n".join(violations)


def test_xdg_paths():
	from red_pill.core.paths import (
		get_thread_state_path,
		get_staging_dir,
		get_ingestion_dir,
		get_swarm_config_path,
		get_model_profiles_path,
	)

	assert ".agent" not in str(get_thread_state_path())
	assert ".agent" not in str(get_staging_dir())
	assert ".agent" not in str(get_ingestion_dir())
	assert ".agent" not in str(get_swarm_config_path())
	assert ".agent" not in str(get_model_profiles_path())


def test_migrate_legacy_agent_dirs(tmp_path, monkeypatch):
	import red_pill.core.paths as core_paths

	legacy_agent = tmp_path / ".agent"
	legacy_agent.mkdir()

	legacy_file = legacy_agent / "thread_state.json"
	legacy_file.write_text('{"test": true}')

	target_file = tmp_path / "new_thread_state.json"

	monkeypatch.setattr(core_paths, "get_thread_state_path", lambda: target_file)
	monkeypatch.setattr(Path, "home", lambda: tmp_path)

	core_paths.migrate_legacy_agent_dirs()

	assert not legacy_file.exists()
	assert target_file.exists()
	assert target_file.read_text() == '{"test": true}'


if __name__ == "__main__":
	test_no_legacy_storage_paths()
	test_xdg_paths()
	print("XDG Compliance Tests Passed.")
