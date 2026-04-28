# Implementation Plan: Enterprise Mode Phase 1 Abstraction (v6.1-A)
**Date**: 2026-03-21

This plan outlines the first phase of abstracting the Red Pill Foundation core to support Enterprise Mode extensions via Inversion of Control (IoC).

## Proposed Changes

### Core Abstractions
- **[NEW]** `src/red_pill/core/providers.py`: Define `BaseTelemetryProvider` ABC and `ProviderRegistry`.
- **[MODIFY]** `src/red_pill/telemetry.py`: Refactor `HardwareSentinel` as a provider and register it as default.

### Swarm Orchestration
- **[MODIFY]** `src/red_pill/swarm/orchestrator.py`: Decouple `_run_minion` from direct `HardwareSentinel` calls using the registry.

### Registry Integration
- **[MODIFY]** `src/red_pill/registry.py`: Add provider initialization hooks.

## Verification Plan
- **Automated**: `tests/test_providers.py` (Verify logic & overrides) + `tests/test_hive.py` (E2E swarm telemetry).
- **Manual**: CLI swarm execution + `check_minion_inbox` validation.
