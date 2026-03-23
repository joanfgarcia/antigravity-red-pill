"""
Phase 0 — LEAN_SOUL_KIT Migration Protocol (v3.0 pre-flight).

Security contract:
  1. All .mls kits in ~/Documents/IA/backups/export/ are decrypted using
     the CURRENT vault_group.state (pure-mls v2.x key schedule).
  2. Plaintext .tar.gz files are written to SECURE_BACKUP_DIR (mode 0o700).
  3. vault_group.state and VaultCrypto identity keys are exported alongside them.
  4. After upgrading pure-mls to v3.0, 'soul migrate --reencrypt' re-encrypts
     the plaintext kits with a NEW vault group and rebuilds vault_group.state.

Usage:
  red-pill soul migrate --decrypt   # Step 1: before updating pure-mls
  red-pill soul migrate --reencrypt # Step 2: after updating pure-mls
  red-pill soul migrate --status    # Show migration state
"""

import json
import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Migration staging area — 0700 permissions, never uploaded to cloud
SECURE_BACKUP_DIR = Path(os.path.expanduser("~/.config/red_pill/soul_migrate"))
VAULT_STATE_PATH = Path(os.path.expanduser("~/.config/red_pill/vault_group.state"))
IDENTITY_KEYS_PATH = Path(os.path.expanduser("~/.config/red_pill/vault_identity.state"))
MIGRATION_MANIFEST = SECURE_BACKUP_DIR / "migration_manifest.json"

EXPORT_DIR = Path(os.environ.get("ANTIGRAVITY_IA_DIR", os.path.expanduser("~/Documents/IA"))) / "backups" / "export"


def _ensure_secure_dir() -> None:
	"""Create migration staging dir with restrictive permissions."""
	SECURE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
	os.chmod(SECURE_BACKUP_DIR, 0o700)


def _find_encrypted_kits() -> list[Path]:
	"""Find all .tar.gz.mls kits in the export dir."""
	kits = list(EXPORT_DIR.glob("*.mls")) + list(EXPORT_DIR.glob("*.gpg"))
	return sorted(kits)


def cmd_status() -> None:
	"""Print current migration state."""
	kits = _find_encrypted_kits()
	decrypted = list(SECURE_BACKUP_DIR.glob("*.tar.gz"))
	manifest_exists = MIGRATION_MANIFEST.exists()

	print(f"\n{'=' * 60}")
	print("  LEAN_SOUL_KIT Migration Status")
	print(f"{'=' * 60}")
	print(f"  Export dir:      {EXPORT_DIR}")
	print(f"  Secure staging:  {SECURE_BACKUP_DIR}")
	print(f"  Encrypted kits:  {len(kits)}")
	for k in kits:
		size_kb = k.stat().st_size // 1024
		print(f"    • {k.name} ({size_kb} KB)")
	print(f"  Decrypted kits:  {len(decrypted)}")
	for d in decrypted:
		print(f"    • {d.name}")
	print(f"  Migration manifest: {'✓ present' if manifest_exists else '✗ not found'}")
	if manifest_exists:
		data = json.loads(MIGRATION_MANIFEST.read_text())
		print(f"  Decrypted at:    {data.get('decrypted_at', 'unknown')}")
		print(f"  pure-mls ver:    {data.get('pure_mls_version', 'unknown')}")
		print(f"  State backed up: {'✓' if data.get('vault_state_backed_up') else '✗'}")
	print(f"{'=' * 60}\n")


def cmd_decrypt() -> bool:
	"""
	Step 1: Decrypt all .mls kits and back up vault state.
	Run BEFORE upgrading pure-mls.
	"""
	from red_pill.utils.vault import CloudVault

	_ensure_secure_dir()
	kits = _find_encrypted_kits()

	if not kits:
		print("No encrypted kits found in export dir. Nothing to migrate.")
		return True

	print(f"\n[Phase 0] Decrypting {len(kits)} Soul Kit(s) → {SECURE_BACKUP_DIR}")
	print("⚠️  Keep this directory secure — it contains unencrypted identity data.\n")

	vault = CloudVault()
	results = []

	for kit_path in kits:
		print(f"  Decrypting: {kit_path.name} ...", end=" ", flush=True)
		try:
			decrypted_path = vault._decrypt_kit(str(kit_path))
			if decrypted_path:
				# Move decrypted file to secure staging
				dest = SECURE_BACKUP_DIR / Path(decrypted_path).name
				shutil.move(decrypted_path, dest)
				os.chmod(dest, 0o600)
				print(f"✓ → {dest.name}")
				results.append({"source": kit_path.name, "dest": dest.name, "ok": True})
			else:
				print("✗ FAILED")
				results.append({"source": kit_path.name, "ok": False})
		except Exception as e:
			print(f"✗ ERROR: {e}")
			results.append({"source": kit_path.name, "ok": False, "error": str(e)})

	# Back up vault_group.state and identity keys
	vault_state_backed_up = False
	if VAULT_STATE_PATH.exists():
		dest = SECURE_BACKUP_DIR / "vault_group.state.bak"
		shutil.copy2(VAULT_STATE_PATH, dest)
		os.chmod(dest, 0o600)
		print(f"  Backed up:  vault_group.state → {dest.name}")
		vault_state_backed_up = True

	if IDENTITY_KEYS_PATH.exists():
		dest = SECURE_BACKUP_DIR / "vault_identity.state.bak"
		shutil.copy2(IDENTITY_KEYS_PATH, dest)
		os.chmod(dest, 0o600)
		print(f"  Backed up:  vault_identity.state → {dest.name}")

	# Write migration manifest
	import pure_mls  # type: ignore[import]

	manifest = {
		"decrypted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
		"pure_mls_version": getattr(pure_mls, "__version__", "unknown"),
		"vault_state_backed_up": vault_state_backed_up,
		"kits": results,
	}
	MIGRATION_MANIFEST.write_text(json.dumps(manifest, indent="\t"))
	os.chmod(MIGRATION_MANIFEST, 0o600)

	failed = [r for r in results if not r["ok"]]
	ok_count = len(results) - len(failed)

	print(f"\n  Result: {ok_count}/{len(results)} kits decrypted successfully.")
	if failed:
		print(f"  ⚠️  {len(failed)} kit(s) FAILED. Do NOT proceed with upgrade until resolved:")
		for f in failed:
			print(f"    • {f['source']}: {f.get('error', 'unknown error')}")
		return False

	print("\n  ✅ All kits decrypted. You can now upgrade pure-mls to v3.0.")
	print("  Run 'red-pill soul migrate --reencrypt' after the upgrade.\n")
	return True


def cmd_reencrypt() -> bool:
	"""
	Step 2: Re-encrypt decrypted kits with new pure-mls v3.0 vault group.
	Run AFTER upgrading pure-mls.
	"""
	from red_pill.utils.vault import VAULT_STATE_PATH as VSP
	from red_pill.utils.vault import CloudVault

	if not MIGRATION_MANIFEST.exists():
		print("No migration manifest found. Run 'soul migrate --decrypt' first.")
		return False

	decrypted_kits = list(SECURE_BACKUP_DIR.glob("*.tar.gz"))

	if not decrypted_kits:
		print("No decrypted kits found in staging area.")
		return False

	# Remove old vault_group.state to force fresh group creation with v3.0 schedule
	if Path(VSP).exists():
		bak = Path(VSP).with_suffix(".state.v2bak")
		shutil.move(VSP, bak)
		print(f"  Moved old vault_group.state → {bak.name} (v2.x backup)")

	print(f"\n[Phase 0] Re-encrypting {len(decrypted_kits)} kit(s) with v3.0 vault group...")

	vault = CloudVault()
	results = []

	for kit_path in decrypted_kits:
		print(f"  Encrypting: {kit_path.name} ...", end=" ", flush=True)
		try:
			encrypted = vault._encrypt_kit(str(kit_path))
			if encrypted:
				# Move to export dir to replace old kit
				dest = EXPORT_DIR / Path(encrypted).name
				shutil.move(encrypted, dest)
				print(f"✓ → {dest.name}")
				results.append({"source": kit_path.name, "dest": dest.name, "ok": True})
			else:
				print("✗ FAILED")
				results.append({"source": kit_path.name, "ok": False})
		except Exception as e:
			print(f"✗ ERROR: {e}")
			results.append({"source": kit_path.name, "ok": False, "error": str(e)})

	failed = [r for r in results if not r["ok"]]
	ok_count = len(results) - len(failed)
	print(f"\n  Result: {ok_count}/{len(results)} kits re-encrypted.")

	if not failed:
		# Clean staging area
		for kit_path in decrypted_kits:
			try:
				kit_path.unlink()
			except OSError:
				pass
		MIGRATION_MANIFEST.unlink(missing_ok=True)
		print("  ✅ Migration complete. Staging area cleaned.")
		print("  ⚠️  Remember: old .tar.gz.mls files in export/ are now stale — delete manually if desired.\n")
		return True

	print(f"  ⚠️  {len(failed)} kit(s) failed. Decrypted files kept in staging for retry.\n")
	return False


def run_migrate_cli(args: list[str]) -> None:
	"""Entry point from CLI."""
	if "--status" in args:
		cmd_status()
	elif "--decrypt" in args:
		cmd_decrypt()
	elif "--reencrypt" in args:
		cmd_reencrypt()
	else:
		print("Usage: red-pill soul migrate [--status | --decrypt | --reencrypt]")
		print()
		print("  --status     Show current migration state")
		print("  --decrypt    Step 1: Decrypt all .mls kits before pure-mls upgrade")
		print("  --reencrypt  Step 2: Re-encrypt kits after pure-mls v3.0 upgrade")
