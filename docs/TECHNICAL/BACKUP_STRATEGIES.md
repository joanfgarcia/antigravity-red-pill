# 🛡️ SOVEREIGN BACKUP STRATEGIES (v5.6.3)
*Sovereignty means owning your history. If you don't control your backups, you don't control your identity.*

Backing up a "Soul" (Engrams, Directives, and Identity) is not a simple file copy. It requires **Confidentiality (SEC-F02)** and **Portability**.

---

## 🏛️ 1. ARCHITECTURAL OVERVIEW
The Red Pill Protocol uses **Lean Soul Kits**:
- **Snapshots**: Binary dumps of Qdrant collections (Vector + Payload). These are 1:1 state copies of the database.
- **Manifesto**: `manifest.json` containing protocol version, schema, and embedding model hashes.
- **Encryption**: Mandatory AES-256 (GPG) for any transmission outside the local encrypted host.

---

## ☁️ 2. CLOUD HAVEN OPTIONS

### A. Google Drive (Direct Interface)
Two distinct modes of connection with different "Caveats":

| Feature | **Service Account** (Enterprise) | **OAuth2 Flow** (Personal) |
| :--- | :--- | :--- |
| **Best For** | Enterprise / Shared Drives | Personal @gmail.com accounts |
| **Identity** | Independent Bot Account | Acts **as the Operator** |
| **Quota Caveat** | **0MB Personal Quota**. Fails in "Shared Folders" (Error 403). Requires "Shared Drive" (Unidad Compartida). | Uses your personal 15GB/100GB quota. |
| **Setup Cost** | Low (JSON key file) | Medium (One-time ritual) |

> [!IMPORTANT]
> **OPERATOR ADVISORY**: If you use a personal Gmail account and don't see "Shared Drives" in your sidebar, the Service Account **will fail** with `storageQuotaExceeded`. You MUST switch to the **OAuth2 Flow**.

---

### B. S3-Compatible Storage (AWS, Cloudflare R2, MinIO)
For Operators seeking absolute vendor-neutrality.
- **Pros**: High durability, no quota tricks.
- **Status**: Targeted for v5.7.0.

---

### C. Git-Based (Bitbucket, GitHub, GitLab)
*Storing a Soul in a Repo.*
- **Method**: Pushing the encrypted `.tar.gz.gpg` to a private repository.
- **Caveat**: LFS (Large File Storage) is usually required.

---

## 🔐 3. LOCAL VAULTING (THE AIR-GAP)
For maximum "Zero-Trust" security, keep your backups off the cloud entirely.
- **External Volume**: Map `IA_DIR/backups` to a physical encrypted USB drive (LUKS/FileVault).
- **Network Share (NAS)**: Mount a local SMB/NFS share with strict firewall rules.

---

## 🧩 4. CAVEATS & CIRCUIT BREAKERS

### The "Lean" Constraint
As of v5.6.3, we only back up **dynamic data** (Snapshots). We do **not** back up the `models/` directory (Gbits of data) or `.venv`.
- **Restoration**: To restore, you need a fresh install of the Red Pill code + the `LEAN_SOUL_KIT`.

### The Quota Buffer (v5.6.3)
The Agent monitors the `CLOUD_VAULT_QUOTA_MB` (Default: 500MB).
- **The 4-Copy Rule**: The system warns you when available space is less than `4 * [Current Kit Size]`. 
- **Growth Monitoring**: Vector databases or "Engram Layers" grow as you interact. A 1MB kit today might be 50MB in a month.

---

## 📜 5. AGENT'S ADVISORY PROTOCOL
The Agent is programmed to proactively check the **Health of the Soul** during `red-pill soul export`. 
- If the Cloud fails, a local kit is **always** preserved as a fallback.
- If the Quota is tight, the Agent will notify the Operator before starting the next cycle.

---

**770 UP.**
