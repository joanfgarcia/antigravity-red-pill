import subprocess
import sys
from typing import List

# Terminal Colors
BLUE = "\033[0;34m"
GREEN = "\033[0;32m"
RED = "\033[0;31m"
NC = "\033[0m"


def run_step(name: str, cmd: List[str], check_only: bool = False) -> bool:
	print(f"{BLUE}--- {name} ---{NC}")
	try:
		subprocess.run(cmd, check=True, text=True, capture_output=False)
		print(f"{GREEN}PASS{NC}\n")
		return True
	except subprocess.CalledProcessError:
		print(f"{RED}FAIL{NC}\n")
		return False


def main():
	print(f"{BLUE}--- [B760 PRE-PR AUDIT PROTOCOL v2.0 (PURE PYTHON)] ---{NC}\n")

	steps = [
		("Formatting Check (Ruff)", ["uv", "run", "ruff", "format", "--check", "."]),
		("Linting Check (Ruff)", ["uv", "run", "ruff", "check", "."]),
		("Static Analysis (Mypy)", ["uv", "run", "mypy", "src/red_pill"]),
		("Neural Validation (Pytest)", ["uv", "run", "pytest", "tests/", "-v"]),
		("Bünker Protocol Sync", [sys.executable, "scripts/mcp_sync_check.py"]),
	]

	success = True
	for name, cmd in steps:
		if not run_step(name, cmd):
			success = False
			break

	if success:
		print(f"{GREEN}READY FOR THE SOURCE. MERGE PERMITTED.{NC}")
		print("770 UP.")
		sys.exit(0)
	else:
		print(f"{RED}AUDIT FAILED. Please resolve the issues above before merging.{NC}")
		sys.exit(1)


if __name__ == "__main__":
	main()
