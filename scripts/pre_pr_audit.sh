#!/bin/bash
# Pre-PR Audit Protocol v1.0
# Verifies coding standards, typing, and system integrity before any merge.

set -e # Exit on error

# Terminal Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}--- [B760 PRE-PR AUDIT PROTOCOL] ---${NC}"

# 1. Formatting Check
echo -ne "1. Formatting (Ruff)... "
uv run ruff format --check . 2>/dev/null && echo -e "${GREEN}PASS${NC}" || (echo -e "${RED}FAIL (Run: uv run ruff format .)${NC}"; exit 1)

# 2. Linting Check
echo -ne "2. Linting (Ruff)... "
uv run ruff check . 2>/dev/null && echo -e "${GREEN}PASS${NC}" || (echo -e "${RED}FAIL (Run: uv run ruff check --fix .)${NC}"; exit 1)

# 3. Type Checking
echo -e "3. Static Analysis (Mypy)..."
# We run mypy and filter only critical errors if needed, but here we go full strict.
uv run mypy src/red_pill --ignore-missing-imports && echo -e "${GREEN}TYPING PASS${NC}" || (echo -e "${RED}TYPING FAIL${NC}"; exit 1)

# 4. Unit & Integration Tests
echo -e "4. Neural Validation (Pytest)..."
uv run pytest tests/test_daemon.py tests/test_memory.py tests/test_version_sync.py -v && echo -e "${GREEN}TESTS PASS${NC}" || (echo -e "${RED}TESTS FAIL${NC}"; exit 1)

echo -e "\n${GREEN}READY FOR THE SOURCE. MERGE PERMITTED.${NC}"
echo -e "770 UP."
