#!/bin/bash
set -eo pipefail

echo "--- LM-005: E2E Integration Persistence Test ---"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Using a unique local directory to avoid permission collisions
QDRANT_VOL="$SCRIPT_DIR/qdrant_test_data_$(date +%s)"

mkdir -p "$QDRANT_VOL"

cd "$SCRIPT_DIR"

# Update docker-compose.test.yml to use the unique volume path
# We use a temporary file to avoid modifying the original during the test if needed, 
# but here we just use sed locally.
sed -i "s|/tmp/qdrant_test_vol|$QDRANT_VOL|g" docker-compose.test.yml

echo "[1/4] Starting ephemeral Qdrant container..."
docker compose -f docker-compose.test.yml up -d
sleep 5 # Give more time for Qdrant to initialize

echo "[2/4] Seeding a test point via Red Pill API..."
cat << 'EOF' > /tmp/test_inject.py
from red_pill.memory import MemoryManager
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import red_pill.config as cfg

manager = MemoryManager(url="http://localhost:6339")
client = manager.client

client.recreate_collection(
    collection_name="integration_test",
    vectors_config=VectorParams(size=384, distance=Distance.COSINE)
)

manager.add_memory("integration_test", "This is an integration test memory that must survive.", point_id="11111111-1111-1111-1111-111111111111")
EOF

cd ../../
uv run python3 /tmp/test_inject.py

echo "[3/4] Destroying the Qdrant container (Simulating crash/update)..."
cd "$SCRIPT_DIR"
docker compose -f docker-compose.test.yml stop
docker compose -f docker-compose.test.yml rm -f

echo "[4/4] Restarting container and reading persistent volume..."
docker compose -f docker-compose.test.yml up -d
sleep 5

cat << 'EOF' > /tmp/test_verify.py
from qdrant_client import QdrantClient
import sys

client = QdrantClient(url="http://localhost:6339")
try:
    hits = client.retrieve("integration_test", ids=["11111111-1111-1111-1111-111111111111"], with_payload=True)
    # Corrected key from 'text_chunk' to 'content' (DS-004)
    if hits and hits[0].payload.get("content") == "This is an integration test memory that must survive.":
        print("SUCCESS LM-005: Integrations test passed. Memory survived container destruction.")
        sys.exit(0)
    else:
        print(f"FAILED: Memory was corrupted or not found. Hits: {hits}")
        sys.exit(1)
except Exception as e:
    print(f"FAILED: Missing collection or exception: {e}")
    sys.exit(1)
EOF

cd ../../
uv run python3 /tmp/test_verify.py

# Cleanup
echo "Cleaning up ephemeral environment..."
cd "$SCRIPT_DIR"
docker compose -f docker-compose.test.yml down -v
# Restore the template path in the compose file
sed -i "s|$QDRANT_VOL|/tmp/qdrant_test_vol|g" docker-compose.test.yml
rm -rf "$QDRANT_VOL"
rm /tmp/test_inject.py /tmp/test_verify.py

echo "--- Integration Test Complete ---"
