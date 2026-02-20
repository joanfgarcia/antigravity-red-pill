#!/bin/bash
# Red Pill Protocol: Preparation for Technical Audit
# Aggregates all source code into a single file for external LLM evaluation.

OUTPUT_FILE="proyecto_completo.txt"

echo "Aggregating project core into $OUTPUT_FILE using git-aware discovery..."

# Use git ls-files to respect .gitignore and only include relevant source files.
# Includes both cached (tracked) and other (untracked but not ignored) files.
git ls-files --cached --others --exclude-standard | grep -vE '\.(png|jpg|jpeg|gif|pdf|ico)$' | while read f; do
	if [ "$f" != "$OUTPUT_FILE" ] && [ -f "$f" ]; then
		echo -e "\n\n===== FILE: $f =====\n"
		cat "$f"
	fi
done > "$OUTPUT_FILE"

echo "Done. Standard audit prompt available in docs/technical/CERTIFICATION_PROTOCOL.md"
