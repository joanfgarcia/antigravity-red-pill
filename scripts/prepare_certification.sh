#!/bin/bash
# Red Pill Protocol: Preparation for Technical Audit
# Aggregates all source code into a single file for external LLM evaluation.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR" || exit 1

CORE_OUTPUT="RED_PILL_DIGEST_CORE.txt"
TESTS_OUTPUT="RED_PILL_DIGEST_TESTS.txt"
LORE_OUTPUT="RED_PILL_DIGEST_LORE.txt"

echo "Aggregating project digests..."

# NOTE: docs/CERTIFICATION/ is intentionally EXCLUDED from the digest.
# Including past audit reports in the digest sent to auditors would contaminate
# their analysis with prior findings, causing confirmation bias and hallucinations
# (e.g., rating a fixed issue as still broken because a previous report said so).
# Auditors must evaluate the code as-is, not through the lens of past verdicts.
CORE_FILES=$(git ls-files src/red_pill/ scripts/ docs/TECHNICAL/ pyproject.toml README.md docker/ | grep -vE '\.(png|jpg|jpeg|gif|pdf|ico|coverage|DS_Store|lock|pyc|db|db-wal|db-shm)$')
TESTS_FILES=$(git ls-files tests/ | grep -vE '\.(png|jpg|jpeg|gif|pdf|ico|coverage|DS_Store|lock|pyc|db|db-wal|db-shm)$')
LORE_FILES=$(git ls-files docs/LORE/ CHANGELOG.md docs/GUIDES/ docs/CORE/ seeds/ skills/ | grep -vE '\.(png|jpg|jpeg|gif|pdf|ico|coverage|DS_Store|lock|pyc|db|db-wal|db-shm)$')

generate_digest() {
	local output_file=$1
	local target_files=$2
	
	echo "Generating $output_file..."
	echo -e "================================================================================\n							RED PILL SOURCE DIGEST INDEX						\n================================================================================\n" > "$output_file"
	
	local matched_files=()
	for f in $target_files; do
		if [ "$f" != "$CORE_OUTPUT" ] && [ "$f" != "$TESTS_OUTPUT" ] && [ "$f" != "$LORE_OUTPUT" ] && [ "$f" != ".env" ] && [ -f "$f" ]; then
			matched_files+=("$f")
			echo "- $f" >> "$output_file"
		fi
	done
	
	echo -e "\n================================================================================\n" >> "$output_file"
	
	for f in "${matched_files[@]}"; do
		echo -e "\n\n===== FILE: $f =====\n" >> "$output_file"
		sed -E 's/(ghp_[A-Za-z0-9]+|gho_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+)/[REDACTED_GH_TOKEN]/g' "$f" >> "$output_file"
	done
}

generate_digest "$CORE_OUTPUT" "$CORE_FILES"
generate_digest "$TESTS_OUTPUT" "$TESTS_FILES"
generate_digest "$LORE_OUTPUT" "$LORE_FILES"

echo "Done. Digests generated:"
echo "- $CORE_OUTPUT"
echo "- $TESTS_OUTPUT"
echo "- $LORE_OUTPUT"
