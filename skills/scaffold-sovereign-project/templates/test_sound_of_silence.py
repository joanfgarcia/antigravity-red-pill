import subprocess
import sys

def test_sound_of_silence_linter():
    """Enforces the Protocol of Silence by running ruff check during pytest."""
    try:
        result = subprocess.run(
            ["ruff", "check", "src/", "tests/"],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print("Protocol of Silence violation detected by Ruff:")
        print(e.stdout)
        print(e.stderr)
        sys.exit(1)
