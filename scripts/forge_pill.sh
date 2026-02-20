#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARING_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$(cd "$SHARING_ROOT/.." && pwd)"
OUTPUT_FILE="$OUTPUT_DIR/red_pill_distribution.tar.gz"

find "$SHARING_ROOT" -name "*.pyc" -delete
find "$SHARING_ROOT" -name "__pycache__" -delete

tar -C "$SHARING_ROOT" -czf "$OUTPUT_FILE" .
echo -e "Artifact: ${OUTPUT_FILE}"
