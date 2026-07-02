"""Regression tests for install_neo.sh shell logic.

Validates critical conditional logic extracted from the install script,
particularly the CHANGE_SKIN / SKIP_BOOTSTRAP flow that was broken by
an accidental negation removal in an earlier patch.
"""

import subprocess
from pathlib import Path

INSTALL_SCRIPT = Path(__file__).parent.parent / "scripts" / "install_neo.sh"


class TestChangeSkinLogic:
	"""
	Regression guard for the CHANGE_SKIN conditional.

	The logic must be:
		Question: "Re-inicializar Identidad y Skin? (s/N)"
		- User says "S" (yes, re-initialize) -> SKIP_BOOTSTRAP stays false -> wizard runs
		- User says "N" or empty (no, preserve) -> SKIP_BOOTSTRAP=true -> wizard skipped

	A previous patch accidentally removed the `!` negation, inverting this behavior.
	"""

	@staticmethod
	def _run_skin_logic(change_skin_value: str) -> str:
		"""
		Run the extracted CHANGE_SKIN logic in an isolated bash snippet.
		Returns the value of SKIP_BOOTSTRAP after the conditional.
		"""
		# This mirrors the exact logic from install_neo.sh lines 303-312
		script = f"""
		SKIP_BOOTSTRAP=false
		CHANGE_SKIN="{change_skin_value}"
		if [[ ! "${{CHANGE_SKIN:-}}" =~ ^[Ss]$ ]]; then
			SKIP_BOOTSTRAP=true
		fi
		echo "$SKIP_BOOTSTRAP"
		"""
		result = subprocess.run(
			["bash", "-c", script],
			capture_output=True,
			text=True,
			timeout=5,
		)
		return result.stdout.strip()

	def test_user_says_yes_does_not_skip(self):
		"""When user says 'S' (re-initialize), SKIP_BOOTSTRAP must remain false."""
		assert self._run_skin_logic("S") == "false"
		assert self._run_skin_logic("s") == "false"

	def test_user_says_no_skips_bootstrap(self):
		"""When user says 'N' or anything else, SKIP_BOOTSTRAP must be true."""
		assert self._run_skin_logic("N") == "true"
		assert self._run_skin_logic("n") == "true"

	def test_empty_input_skips_bootstrap(self):
		"""When user presses Enter (empty, default N), SKIP_BOOTSTRAP must be true."""
		assert self._run_skin_logic("") == "true"

	def test_random_input_skips_bootstrap(self):
		"""Any non-S input should default to skip (preserve current skin)."""
		assert self._run_skin_logic("x") == "true"
		assert self._run_skin_logic("yes") == "true"  # Only single char 's'/'S' counts


class TestInstallScriptSyntax:
	"""Basic syntax validation of install_neo.sh."""

	def test_script_exists(self):
		assert INSTALL_SCRIPT.exists(), f"install_neo.sh not found at {INSTALL_SCRIPT}"

	def test_script_bash_syntax_check(self):
		"""Run bash -n (syntax check only) on the install script."""
		result = subprocess.run(
			["bash", "-n", str(INSTALL_SCRIPT)],
			capture_output=True,
			text=True,
			timeout=10,
		)
		assert result.returncode == 0, f"Syntax errors in install_neo.sh: {result.stderr}"

	def test_change_skin_negation_present(self):
		"""
		Regression guard: The CHANGE_SKIN conditional MUST contain the `!` negation.
		Without it, the logic is inverted (saying 'S' to re-initialize actually preserves).
		"""
		content = INSTALL_SCRIPT.read_text()
		# The correct pattern: `if [[ ! "${CHANGE_SKIN:-}" =~ ^[Ss]$ ]]; then`
		assert '! "${CHANGE_SKIN:-}"' in content, (
			"CRITICAL: CHANGE_SKIN conditional is missing the `!` negation operator. This inverts the re-initialization logic."
		)

	def test_skin_consent_negation_present(self):
		"""SKIN_CONSENT must also use negation (deny consent → revert to 760)."""
		content = INSTALL_SCRIPT.read_text()
		assert '! "${SKIN_CONSENT:-}"' in content, "SKIN_CONSENT conditional is missing the `!` negation operator."

	def test_skip_bootstrap_initialized(self):
		"""SKIP_BOOTSTRAP must be initialized before use."""
		content = INSTALL_SCRIPT.read_text()
		lines = content.split("\n")
		init_line = None
		use_line = None
		for i, line in enumerate(lines):
			if "SKIP_BOOTSTRAP=false" in line and not line.strip().startswith("#"):
				init_line = i
			if init_line is None and "SKIP_BOOTSTRAP" in line and "if" in line:
				use_line = i

		assert init_line is not None, "SKIP_BOOTSTRAP is never initialized to false"
		# If use_line is found before init_line, the variable is used before init
		if use_line is not None:
			assert init_line < use_line, f"SKIP_BOOTSTRAP used at line {use_line} before initialization at line {init_line}"
