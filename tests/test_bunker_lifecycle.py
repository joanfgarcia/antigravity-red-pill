import os
from unittest.mock import MagicMock, patch

import yaml

from red_pill.bunker_lifecycle import bunker_export, bunker_restore, detect_hardware, profile_hardware


def test_detect_hardware_no_gpu():
	"""Test hardware detection when no Nvidia GPU is present."""
	with patch("psutil.virtual_memory") as mock_mem, patch("psutil.cpu_count") as mock_cpu, patch("subprocess.run") as mock_run:
		# Mock RAM (16 GB)
		mock_mem_obj = MagicMock()
		mock_mem_obj.total = 16 * (1024**3)
		mock_mem.return_value = mock_mem_obj

		# Mock CPU (4 cores, 8 threads)
		mock_cpu.side_effect = [4, 8]

		# Mock GPU (nvidia-smi fails)
		mock_run.side_effect = FileNotFoundError()

		hw = detect_hardware()

		assert hw["ram_gb"] == 16.0
		assert hw["cpu_cores"] == 4
		assert hw["cpu_threads"] == 8
		assert hw["has_nvidia"] is False
		assert hw["vram_gb"] == 0.0


def test_detect_hardware_with_gpu():
	"""Test hardware detection with Nvidia GPU."""
	with patch("psutil.virtual_memory") as mock_mem, patch("psutil.cpu_count") as mock_cpu, patch("subprocess.run") as mock_run:
		# Mock RAM (32 GB)
		mock_mem_obj = MagicMock()
		mock_mem_obj.total = 32 * (1024**3)
		mock_mem.return_value = mock_mem_obj

		# Mock CPU (8 cores, 16 threads)
		mock_cpu.side_effect = [8, 16]

		# Mock GPU (24GB VRAM)
		mock_result = MagicMock()
		mock_result.returncode = 0
		mock_result.stdout = "24576\n"
		mock_run.return_value = mock_result

		hw = detect_hardware()

		assert hw["ram_gb"] == 32.0
		assert hw["has_nvidia"] is True
		assert hw["vram_gb"] == 24.0


def test_profile_hardware_creation(tmp_path):
	"""Test bunker init profile generation safely in a tmp_path."""
	# We patch IA_DIR so it writes to the isolated tmp_path, preventing real overrides.
	with patch.dict(os.environ, {"IA_DIR": str(tmp_path)}), patch("red_pill.bunker_lifecycle.detect_hardware") as mock_detect:
		mock_detect.return_value = {"ram_gb": 32.0, "cpu_cores": 10, "cpu_threads": 20, "has_nvidia": True, "vram_gb": 12.0}

		profile_hardware()

		profile_file = tmp_path / "bunker.profile.yaml"
		assert profile_file.exists()

		with open(profile_file, "r") as f:
			data = yaml.safe_load(f)

		assert "hardware" in data
		assert data["hardware"]["memory_max_gb"] == 28.0  # 32 - 4
		assert data["hardware"]["workers"] == 8  # capped at 8
		assert data["hardware"]["cuda_enabled"] is True
		assert data["models"]["quantization"] == "INT2"  # > 10GB VRAM triggers INT2


def test_bunker_export_stub(capsys):
	"""Test that the export stub outputs the correct plan."""
	bunker_export()
	captured = capsys.readouterr()
	assert "[BÜNKER EXPORT: SOVEREIGN BACKUP]" in captured.out
	assert "PRAGMA wal_checkpoint" in captured.out
	assert "manifest.json" in captured.out


def test_bunker_restore_stub(capsys):
	"""Test that the restore stub outputs the correct plan safely."""
	# Since it's a stub, it doesn't do anything yet, but we test the skeleton.
	bunker_restore()
	captured = capsys.readouterr()
	assert "[BÜNKER RESTORE: SMART REHYDRATION]" in captured.out
	assert "Decrypting .mls package" in captured.out


def test_bunker_install(tmp_path, monkeypatch):
	import subprocess

	import red_pill.bunker_lifecycle as bl

	config_dir = tmp_path / "config"
	monkeypatch.setattr(bl, "get_config_dir", lambda: config_dir)
	monkeypatch.setattr(bl, "get_bunker_root", lambda: tmp_path)

	env_example = tmp_path / ".env.example"
	env_example.write_text("TEST_VAR=1")

	# Mock scripts
	scripts_dir = tmp_path / "scripts"
	scripts_dir.mkdir()
	(scripts_dir / "schedule_pulse.py").write_text("pass")
	(scripts_dir / "download_slm.py").write_text("pass")

	mock_run = MagicMock()
	mock_run.returncode = 0
	mock_run.stdout = "OK"
	monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_run)

	bl.bunker_install()

	env_file = config_dir / ".env"
	assert env_file.exists()
	assert env_file.read_text() == "TEST_VAR=1"


def test_bunker_update(tmp_path, monkeypatch):
	import shutil
	import subprocess

	import red_pill.bunker_lifecycle as bl

	monkeypatch.setattr(bl, "get_bunker_root", lambda: tmp_path)
	monkeypatch.setattr("red_pill.core.paths.get_bunker_root", lambda: tmp_path)

	(tmp_path / ".git").mkdir()

	mock_run = MagicMock()
	mock_run.returncode = 0
	mock_run.stdout = "Already up to date."
	monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_run)

	monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/uv" if cmd == "uv" else None)
	monkeypatch.setattr(os.path, "exists", lambda path: True if "uv" in path else False)

	bl.bunker_update()


def test_bunker_update_regenerates_daemon_and_skills(tmp_path, monkeypatch):
	"""update must re-run setup_background_model.sh and redeploy skills (success path)."""
	import shutil
	import subprocess

	import red_pill.bunker_lifecycle as bl

	monkeypatch.setattr("red_pill.core.paths.get_bunker_root", lambda: tmp_path)
	(tmp_path / ".git").mkdir()
	(tmp_path / ".env.example").write_text("X=1")

	scripts_dir = tmp_path / "scripts"
	scripts_dir.mkdir()
	(scripts_dir / "setup_background_model.sh").write_text("#!/bin/bash\ntrue\n")

	skill = tmp_path / "skills" / "demo"
	skill.mkdir(parents=True)
	(skill / "SKILL.md").write_text("---\nname: demo\n---\n")

	agent_dir = tmp_path / "agenthome"
	monkeypatch.setenv("RED_PILL_AGENT_DIR", str(agent_dir))

	calls = []

	def fake_run(cmd, *args, **kwargs):
		calls.append(cmd)
		m = MagicMock()
		m.returncode = 0
		m.stdout = "ok"
		m.stderr = ""
		return m

	monkeypatch.setattr(subprocess, "run", fake_run)
	monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

	bl.bunker_update()

	# The generated daemon is regenerated via setup_background_model.sh
	assert any("setup_background_model.sh" in " ".join(map(str, c)) for c in calls if isinstance(c, (list, tuple)))
	# Skills are redeployed to the agent skills dir
	assert (agent_dir / "skills" / "demo" / "SKILL.md").exists()


def test_parse_changelog_release():
	from red_pill.bunker_lifecycle import parse_changelog_release

	changelog = """## [7.15.0] - 2026-07-30 (El Despertar Determinista)

Intro paragraph.

### ⚡ Wake-up determinista
- **[FEAT] algo**

### 🤝 El Acta del Pacto
- **[FEAT] otra cosa**

## [7.14.0] - 2026-07-29 (Chronicle)

### 🧹 Vieja sección
"""
	r = parse_changelog_release(changelog)
	assert r["version"] == "7.15.0"
	assert r["date"] == "2026-07-30"
	assert r["codename"] == "El Despertar Determinista"
	assert r["previous"] == "7.14.0"
	assert "Wake-up determinista" in r["features"]
	assert "El Acta del Pacto" in r["features"]
	assert "Vieja sección" not in r["features"]


def test_parse_changelog_release_empty():
	from red_pill.bunker_lifecycle import parse_changelog_release

	assert parse_changelog_release("no releases here") is None


def test_refresh_protocol_version_engram(tmp_path, monkeypatch):
	"""The engram text is built from the CHANGELOG heading — codename included, never invented."""
	from unittest.mock import MagicMock, patch

	from red_pill import bunker_lifecycle

	(tmp_path / "CHANGELOG.md").write_text("## [9.9.9] - 2099-01-01 (Test Codename)\n\n### Feature One\n\n## [9.9.8] - 2098-12-31 (Old)\n")
	with patch("red_pill.memory.MemoryManager") as mock_mgr:
		ok = bunker_lifecycle.refresh_protocol_version_engram(tmp_path)

	assert ok is True
	kwargs = mock_mgr.return_value.add_memory.call_args.kwargs
	assert kwargs["point_id"] == "00000000-0000-0000-0000-000000000070"
	assert "v9.9.9" in kwargs["text"]
	assert "Codename: Test Codename" in kwargs["text"]
	assert "Previous stable: v9.9.8" in kwargs["text"]
	assert kwargs["force_immune"] is True
