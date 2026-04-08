# CloudSync Plugin

## Overview
Decoupled Google Drive synchronization for Red Pill Soul Kits. This plugin reacts to `SoulCreatedEvent` from the `SoulManager` and uploads newly created, encrypted `.mls` (or `.gpg`) kits to a designated Drive folder.

## Configuration
Located at `<IA_DIR>/plugins/cloud_sync/cloud_sync.json`:

```json
{
    "enabled": true,
    "folder_id": "YOUR_DRIVE_FOLDER_ID",
    "service_account_file": "path/to/service_account.json",
    "client_secrets_file": "path/to/client_secrets.json",
    "quota_mb": 2048,
    "reserve_count": 3
}
```

## Credential Standards (v6.4.1)
This plugin follows the **Sovereign Credential Standard**. The OAuth2 token is strictly stored in:
`~/.agent/credentials/drive_token.json`

## Fail-Safe
If the upload fails (e.g., OAuth2 token expired), the failure is logged and the local encrypted kit remains safe in `<IA_DIR>/backups/export/`.

---
*Part of the Project Echo / Sentinel Infrastructure.*
