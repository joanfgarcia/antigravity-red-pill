"""Tests de la migración instalación/actualización de MEMENTO_PROMPT_LANGUAGE."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "migrate_prompt_language.py"


def _load():
	spec = importlib.util.spec_from_file_location("migrate_prompt_language", SCRIPT)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


mpl = _load()


@pytest.mark.parametrize(
	"env,expected",
	[
		({"LANG": "es_ES.UTF-8"}, "es"),
		({"LANG": "en_US.UTF-8"}, "en"),
		({"LANG": "ca_ES@valencia"}, "ca"),
		({"LANG": "fr_FR.UTF-8"}, "fr"),
		({"LANG": "C"}, "es"),
		({"LANG": "POSIX"}, "es"),
		({"LANG": "ja_JP.UTF-8"}, "es"),
		({"LANG": ""}, "es"),
		({}, "es"),
	],
)
def test_detect_language(env, expected):
	assert mpl.detect_language(env) == expected


def test_precedencia_lc_all_sobre_lang():
	assert mpl.detect_language({"LC_ALL": "en_US.UTF-8", "LANG": "es_ES.UTF-8"}) == "en"
	assert mpl.detect_language({"LC_MESSAGES": "ca_ES.UTF-8", "LANG": "es_ES.UTF-8"}) == "ca"


def test_ensure_escribe_si_falta(tmp_path):
	env_file = tmp_path / "cfg" / ".env"
	env_file.parent.mkdir()
	env_file.write_text("OTRA=1\n", encoding="utf-8")
	action, value = mpl.ensure(env_file, "es")
	assert (action, value) == ("set", "es")
	assert "OTRA=1" in env_file.read_text(encoding="utf-8")
	assert mpl.read_env_value(env_file) == "es"


def test_ensure_preserva_existente(tmp_path):
	env_file = tmp_path / ".env"
	env_file.write_text('MEMENTO_PROMPT_LANGUAGE="en"\n', encoding="utf-8")
	action, value = mpl.ensure(env_file, "es")
	assert (action, value) == ("kept", "en")
	assert env_file.read_text(encoding="utf-8").count("MEMENTO_PROMPT_LANGUAGE") == 1


def test_ensure_idempotente(tmp_path):
	env_file = tmp_path / ".env"
	mpl.ensure(env_file, "es")
	mpl.ensure(env_file, "es")
	assert env_file.read_text(encoding="utf-8").count("MEMENTO_PROMPT_LANGUAGE") == 1


def test_cli_print_no_escribe(tmp_path):
	env_file = tmp_path / ".env"
	out = subprocess.run(
		[sys.executable, str(SCRIPT), "--print", "--env-file", str(env_file)],
		capture_output=True,
		text=True,
		env={"LANG": "ca_ES.UTF-8", "PATH": "/usr/bin:/bin"},
	)
	assert out.returncode == 0
	assert out.stdout.strip() == "ca"
	assert not env_file.exists()


def test_cli_language_explicito(tmp_path):
	env_file = tmp_path / ".env"
	out = subprocess.run(
		[sys.executable, str(SCRIPT), "--language", "fr", "--env-file", str(env_file)],
		capture_output=True,
		text=True,
		env={"LANG": "es_ES.UTF-8", "PATH": "/usr/bin:/bin"},
	)
	assert out.returncode == 0
	assert mpl.read_env_value(env_file) == "fr"


def test_cli_language_invalido_cae_al_detectado(tmp_path):
	env_file = tmp_path / ".env"
	out = subprocess.run(
		[sys.executable, str(SCRIPT), "--language", "klingon", "--env-file", str(env_file)],
		capture_output=True,
		text=True,
		env={"LANG": "en_GB.UTF-8", "PATH": "/usr/bin:/bin"},
	)
	assert out.returncode == 0
	assert mpl.read_env_value(env_file) == "en"
