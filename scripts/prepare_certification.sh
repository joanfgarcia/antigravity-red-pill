#!/bin/bash
# Red Pill Protocol: Preparation for Technical Audit
# Aggregates all source code into a single file for external LLM evaluation.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR" || exit 1

OUTPUT_FILE="RED_PILL_DIGEST.txt" # legacy name
CORE_OUTPUT="RED_PILL_DIGEST_CORE.txt"
TESTS_OUTPUT="RED_PILL_DIGEST_TESTS.txt"

echo "Aggregating project core into $CORE_OUTPUT and $TESTS_OUTPUT from $ROOT_DIR..."

FILES=$(git ls-files --cached --others --exclude-standard | grep -vE '^docs/CERTIFICATION/' | grep -vE '\.(png|jpg|jpeg|gif|pdf|ico|coverage|DS_Store|lock|pyc)$')

generate_digest() {
	local output_file=$1
	local is_test=$2
	
	echo "Generating $output_file..."
	echo -e "================================================================================\n							RED PILL SOURCE DIGEST INDEX						\n================================================================================\n" > "$output_file"
	
	local matched_files=()
	for f in $FILES; do
		if [ "$f" != "$CORE_OUTPUT" ] && [ "$f" != "$TESTS_OUTPUT" ] && [ "$f" != "$OUTPUT_FILE" ] && [ "$f" != ".env" ] && [ -f "$f" ]; then
			local is_match=0
			if [ "$is_test" = "1" ] && echo "$f" | grep -q '^tests/'; then
				is_match=1
			elif [ "$is_test" = "0" ] && ! echo "$f" | grep -q '^tests/'; then
				is_match=1
			fi
			
			if [ $is_match -eq 1 ]; then
				matched_files+=("$f")
				echo "- $f" >> "$output_file"
			fi
		fi
	done
	
	echo -e "\n================================================================================\n" >> "$output_file"
	
	for f in "${matched_files[@]}"; do
		echo -e "\n\n===== FILE: $f =====\n" >> "$output_file"
		sed -E 's/(ghp_[A-Za-z0-9]+|gho_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+)/[REDACTED_GH_TOKEN]/g' "$f" >> "$output_file"
	done
}

generate_digest "$CORE_OUTPUT" 0
generate_digest "$TESTS_OUTPUT" 1

echo "Done. Digests generated:"
echo "- $CORE_OUTPUT"
echo "- $TESTS_OUTPUT"
