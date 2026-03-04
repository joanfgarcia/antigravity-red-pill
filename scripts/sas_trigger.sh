#!/usr/bin/env bash
# Sovereign Alert System (SAS) - Trigger Helper (v5.6.2)

# Usage: ./sas_trigger.sh "Task Name" "Status Message" [--sound]

TASK_NAME=$1
MESSAGE=$2
EXTRA_ARGS=${@:3}

# 1. Trigger Red Pill SAS (Sensory + Memory)
# This writes to directive_memories for Agent turn-zero recovery
$(dirname "$0")/../.venv/bin/python3 $(dirname "$0")/../src/red_pill/cli.py signal "$MESSAGE" --title "SAS: $TASK_NAME" $EXTRA_ARGS

# 2. Console Output
echo "--- [SAS SIGNAL SENT] ---"
echo "Task: $TASK_NAME"
echo "Message: $MESSAGE"
echo "-------------------------"
