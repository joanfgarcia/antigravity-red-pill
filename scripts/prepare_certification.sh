#!/bin/bash
# Red Pill Protocol: Preparation for Technical Audit
# Aggregates all source code into a single file for external LLM evaluation.

OUTPUT_FILE="RED_PILL_DIGEST.txt"

echo "Aggregating project core into $OUTPUT_FILE using git-aware discovery..."

# Use git ls-files to respect .gitignore and only include relevant source files.
git ls-files --cached --others --exclude-standard | grep -vE '\.(png|jpg|jpeg|gif|pdf|ico)$' | while read f; do
	# Explicitly skip .env and the output file itself
	if [ "$f" != "$OUTPUT_FILE" ] && [ "$f" != ".env" ] && [ -f "$f" ]; then
		echo -e "\n\n===== FILE: $f =====\n"
		# Mask GitHub tokens just in case they are hardcoded somewhere
		cat "$f" | sed 's/github_pat_[a-zA-Z0-9]*/[REDACTED_GH_TOKEN]/g'
	fi
done > "$OUTPUT_FILE"

echo "Done. Standard audit prompt available in docs/technical/CERTIFICATION_PROTOCOL.md"
