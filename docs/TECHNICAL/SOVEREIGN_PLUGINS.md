# Sovereign Plugin Architecture (v1.0)

This document defines the standard for plugin development and deployment within the Red Pill ecosystem, ensuring strict separation between immutable code and sovereign configuration/secrets.

## 1. Dual-Path Topology

To maintain repository cleanliness and protect operator privacy, plugins follow a dual-path structure:

| Component | Repository Path (Immutable) | Sovereign Path (Volatile/Secret) |
| :--- | :--- | :--- |
| **Logic & Assets** | `src/red_pill/plugins/{plugin_name}/` | N/A |
| **Configuration** | N/A | `{IA_DIR}/plugins/{plugin_name}/{plugin_name}.json` |
| **Static Defaults** | `src/red_pill/plugins/{plugin_name}/{plugin_name}.json` | (Optional Fallback) |

### 1.1 Implementation Detail
The `SovereignPlugin` base class implements this logic in its `_load_config()` method. It prioritizes the **Sovereign Path** and only falls back to the repository path if the sovereign configuration is missing.

## 2. Security & Sovereignty

### 2.1 Git Exclusion
The root `.gitignore` file explicitly excludes the `plugins/` directory at the repository root:
```gitignore
/plugins/
```
This ensures that any `{IA_DIR}` configuration folders (which usually reside in the repository root for single-instance deployments) are never accidentally committed to version control.

### 2.2 Domain-Specific Data
If a plugin requires its own database or large state files, these MUST be stored under `{IA_DIR}/storage/plugins/{plugin_name}/` and never within the `src/` directory.

## 3. Developer Guidelines

1. **Clean Sources**: Never write to the `src/` directory at runtime.
2. **Absolute Resolution**: Use `red_pill.config.IA_DIR` to resolve absolute paths for credentials or logs.
3. **No Secrets in Repo**: Ensure that ANY `*.json` or `*.key` files created during development are placed in the sovereign `plugins/` folder immediately.
