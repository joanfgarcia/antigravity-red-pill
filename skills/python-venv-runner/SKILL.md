---
name: python-venv-runner
description: Automatically detects and utilizes virtual environments to execute Python scripts without path-amnesia.
---

# Python Venv Runner

This skill ensures that Python scripts are executed within the context of their project's virtual environment (venv, .venv, etc.) to prevent "command not found" errors and dependency mismatches.

## When to use

- Every time you need to execute a `.py` script or run a `python` command.
- Especially useful in the Bünker when switching between different experimental directories (e.g. BitNet, Samantha, etc.).

## How to use

1.  **Check for existence**: Before running a script, look for common venv directories in the current working directory or its children: `venv`, `.venv`, `experimental/BitNet/venv`.
2.  **Verify binary**: Locate the python binary at `<venv-path>/bin/python`.
3.  **Execute**: Replace generic `python` or `python3` command with the absolute path to the venv binary.

### Preferred Command Format

```bash
# Instead of:
python script.py

# Use:
./venv/bin/python script.py
```

## Troubleshooting

If no venv is found, fall back to `python3` and check if the user has `uv` or `conda` available as a secondary environment manager.
