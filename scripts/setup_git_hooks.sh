#!/bin/bash
# Sovereign Git Hooks Installation Script

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -d "$REPO_ROOT/scripts/git-hooks" ] && [ -d "$REPO_ROOT/.git" ]; then
	echo "Installing Sovereign Git Hooks..."
	mkdir -p "$REPO_ROOT/.git/hooks"
	cp "$REPO_ROOT/scripts/git-hooks/"* "$REPO_ROOT/.git/hooks/"
	chmod +x "$REPO_ROOT/.git/hooks/"*
	echo "Done. Main branch and Force Push are now protected."
else
	echo "Error: .git directory or scripts/git-hooks not found."
	exit 1
fi
