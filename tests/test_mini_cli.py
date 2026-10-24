"""CLI `red-pill mini` — parser, one-shot y REPL con bridge fake."""

from types import SimpleNamespace

from red_pill.cli_parser import build_parser
from red_pill.cli_services import run_mini_cli


class FakeBridge:
	profile = "forge"
	continuity_id = "alma-cli"

	def __init__(self, ok=True, error=None):
		self.calls = []
		self.ok = ok
		self.error = error

	def prompt(self, text):
		self.calls.append(text)
		return SimpleNamespace(ok=self.ok, response=f"echo:{text}", error=self.error)


def test_parser_accepts_mini_once():
	parser, _ = build_parser()
	args = parser.parse_args(["mini", "--once", "hola", "--profile", "loom"])
	assert args.command == "mini"
	assert args.once == "hola"
	assert args.profile == "loom"
	assert args.mission == "mission:mini-cli"


def test_run_once_prints_response():
	out = []
	bridge = FakeBridge()
	run_mini_cli(bridge, once="hola", output=out.append)
	assert out == ["echo:hola"]


def test_repl_reads_until_exit():
	out = []
	lines = iter(["uno", "dos", "exit"])
	bridge = FakeBridge()
	run_mini_cli(bridge, input_fn=lambda _: next(lines), output=out.append)
	assert bridge.calls == ["uno", "dos"]
	assert out[0].startswith("[mini]")
	assert "echo:uno" in out and "echo:dos" in out


def test_run_once_reports_error():
	out = []
	run_mini_cli(FakeBridge(ok=False, error="boom"), once="x", output=out.append)
	assert "boom" in out[0]
