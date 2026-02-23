# TEST SUITE: The Training Simulation

**"I know Kung Fu."**
This document outlines the training programs available to verify the integrity of the Red Pill Protocol.

## 1. Unit Tests (The Dojo)
**Objective**: Verify functional correctness of individual components.
**Tools**: `pytest`, `pytest-cov`
**Coverage Status**: >80% Core Logic (memory.py, schemas.py, seed.py, config.py). `cli.py` and `memory_daemon.py` are excluded from unit test coverage targets as they are integration points.

```bash
# Run the standard test suite with coverage
uv run pytest --cov=src/red_pill tests/
```

## 2. Stress Tests (Agent Smith)
**Objective**: Break the system under load, concurrency, and malicious input.
**Tools**: `tests/stress_test_smith.py`

### Scenarios:
- **The Clone Army**: 100 concurrent threads attacking a single memory ID. Verifies race conditions.
- **Poison Pill**: Injection of malformed JSON, SQL strings, and massive payloads. Verifies Pydantic schema validation.
- **Erosion Flood**: Rapid-fire decay cycles during heavy read operations. Verifies database locking.

```bash
# Execute the stress test (Warning: High Load)
uv run python3 tests/stress_test_smith.py
```
*Audit Report available in [SMITH_AUDIT.md](SMITH_AUDIT.md)*

## 3. Installation Verification (The Keymaker)
**Objective**: Verify that a clean installation works for a new user.
**Tools**: `tests/Dockerfile.keymaker`

This test builds a Docker container from scratch, installs `red-pill` via `pip`, and attempts to connect to the host's Qdrant instance.

```bash
# Build the test container
podman build -t keymaker-test -f tests/Dockerfile.keymaker .

# Run the diagnostic check (requires host networking)
podman run --network host keymaker-test red-pill diag work
```

## 4. Manual Audits
- **Architecture**: `ARCHITECTURE.md` (Scalability Analysis)
- **Security**: `SECURITY.md` (Vulnerability Reporting)
