import os
import subprocess
import sys


def main():
	sharing_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	scratch_dir = os.path.join(sharing_dir, "scratch")
	os.makedirs(scratch_dir, exist_ok=True)
	out_file = os.path.join(scratch_dir, "pre_pr_audit_output.txt")

	with open(out_file, "w") as f:
		f.write("=== PRE-PR AUDIT DIAGNOSTICS ===\n")
		f.flush()

		# Formatting check
		f.write("\n--- Formatting Check (Ruff) ---\n")
		f.flush()
		try:
			res = subprocess.run(["uv", "run", "ruff", "format", "--check", "."], cwd=sharing_dir, capture_output=True, text=True)
			f.write(f"Return code: {res.returncode}\n")
			f.write(res.stdout or "")
			f.write(res.stderr or "")
		except Exception as e:
			f.write(f"Error running Ruff format: {e}\n")
		f.flush()

		# Linting check
		f.write("\n--- Linting Check (Ruff) ---\n")
		f.flush()
		try:
			res = subprocess.run(["uv", "run", "ruff", "check", "."], cwd=sharing_dir, capture_output=True, text=True)
			f.write(f"Return code: {res.returncode}\n")
			f.write(res.stdout or "")
			f.write(res.stderr or "")
		except Exception as e:
			f.write(f"Error running Ruff check: {e}\n")
		f.flush()

		# Static analysis
		f.write("\n--- Static Analysis (Mypy) ---\n")
		f.flush()
		try:
			res = subprocess.run(["uv", "run", "mypy", "src/red_pill"], cwd=sharing_dir, capture_output=True, text=True)
			f.write(f"Return code: {res.returncode}\n")
			f.write(res.stdout or "")
			f.write(res.stderr or "")
		except Exception as e:
			f.write(f"Error running Mypy: {e}\n")
		f.flush()

		# Pytest check
		f.write("\n--- Pytest Check ---\n")
		f.flush()
		try:
			res = subprocess.run(["uv", "run", "pytest", "tests/", "-v"], cwd=sharing_dir, capture_output=True, text=True)
			f.write(f"Return code: {res.returncode}\n")
			f.write(res.stdout or "")
			f.write(res.stderr or "")
		except Exception as e:
			f.write(f"Error running Pytest: {e}\n")
		f.flush()

		f.write("\n=== DIAGNOSTICS COMPLETE ===\n")
		f.flush()

	sys.exit(0)


if __name__ == "__main__":
	main()
