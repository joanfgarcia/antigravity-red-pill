"""HealerMinion safety: the auto-healer must never write broken code to disk.

Root cause of the 24-jul incident: _clean_correction() stripped the leading
indentation off LLM corrections (leaving them at column 0 -> SyntaxError) and
_heal_file() wrote the result without any parse check. The hourly wake pulse
then re-mutilated the same files every run, and the 03:00 sleep cycle died on
'return' outside function (distiller.py).
"""

from unittest.mock import MagicMock

from red_pill.swarm.agents.healer import HealerMinion


def test_clean_correction_preserves_indentation():
	healer = HealerMinion()
	assert healer._clean_correction("\t\treturn _make_fallback()  # type: ignore\n") == "\t\treturn _make_fallback()  # type: ignore"
	assert healer._clean_correction("```python\n\t\tx: int = 1\n```") == "\t\tx: int = 1"
	assert healer._clean_correction("    indented = True") == "    indented = True"


def test_heal_file_reindents_column_zero_corrections(tmp_path):
	"""Even if the LLM loses the indentation, the original line's indent is re-applied."""
	target = tmp_path / "mod.py"
	target.write_text("def f():\n\tvalue = compute()\n\treturn value\n")

	healer = HealerMinion()
	engine = MagicMock()
	engine.synthesize.return_value = "value: int = compute()"  # column 0, would break

	fixes = healer._heal_file(str(target), [{"line": 2, "msg": "Need type annotation"}], engine, dry_run=False)

	assert fixes == 1
	content = target.read_text()
	assert "\tvalue: int = compute()" in content
	compile(content, str(target), "exec")  # still valid python


def test_heal_file_syntax_gate_discards_broken_result(tmp_path):
	"""If the healed source does not parse, the file on disk stays untouched."""
	original = "def f():\n\tif ready:\n\t\treturn 1\n\treturn 0\n"
	target = tmp_path / "mod.py"
	target.write_text(original)

	healer = HealerMinion()
	engine = MagicMock()
	engine.synthesize.return_value = "\t\treturn 1 if else"  # syntactically invalid

	fixes = healer._heal_file(str(target), [{"line": 3, "msg": "bad return"}], engine, dry_run=False)

	assert fixes == 0
	assert target.read_text() == original
