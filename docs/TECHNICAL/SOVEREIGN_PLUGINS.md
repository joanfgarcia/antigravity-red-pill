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

## 4. Sentinel Metabolism Plugins (Health Checks)

The `SentinelAuditor` dynamically discovers and executes health checks using a Registry Pattern, allowing the community or the operator to add service-specific health checks without modifying the core `auditor.py`.

### 4.1 Creating a Health Plugin
Drop a new Python file in `src/red_pill/metabolism/sentinel_plugins/`. The file must contain a class that inherits from `SentinelPlugin` and implements:
- `name`: Display name.
- `is_enabled(cfg)`: Auto-discovery logic (check `config.py` flags).
- `audit(cfg)`: Returns a list of `AuditFinding` objects.
- `heal(cfg, finding)`: Attempts an automated remediation step (e.g., `subprocess.run(["systemctl", "restart", "..."])`).

### 4.2 Auto-Discovery
`pkgutil` and `importlib` automatically load all plugins during `audit_vitals()`.
