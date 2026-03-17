import base64
import json
import os
from typing import Dict, Optional, Tuple, Union

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class SwarmCrypto:
	"""
	Handles End-to-End Encryption (E2E) and Digital Signatures for Swarm.
	v3.5: Supports Unified Identity (Seed -> X25519 + Ed25519).
	Uses X25519 for Key Agreement (PFS) and Ed25519 for Notarization (Signatures).
	"""

	@staticmethod
	def generate_x25519_keypair() -> Tuple[bytes, bytes]:
		"""Generates an X25519 private/public key pair (bytes)."""
		private_key = x25519.X25519PrivateKey.generate()
		public_key = private_key.public_key()

		# For unified identity, we expose the underlying 32-byte seed if needed,
		# but here we follow standard raw output.
		priv_bytes = private_key.private_bytes(
			encoding=serialization.Encoding.Raw, format=serialization.PrivateFormat.Raw, encryption_algorithm=serialization.NoEncryption()
		)
		pub_bytes = public_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
		return priv_bytes, pub_bytes

	@staticmethod
	def generate_unified_identity(seed: Optional[bytes] = None) -> Dict[str, bytes]:
		"""
		Generates a unified identity: one seed results in both X25519 and Ed25519 pairs.
		This ensures a singular identity for both encryption and signatures.
		"""
		actual_seed = seed if seed else os.urandom(32)

		# Deriving X25519 (Encryption)
		x_priv = x25519.X25519PrivateKey.from_private_bytes(actual_seed)
		x_pub = x_priv.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)

		# Deriving Ed25519 (Signatures)
		ed_priv = ed25519.Ed25519PrivateKey.from_private_bytes(actual_seed)
		ed_pub = ed_priv.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)

		return {"seed": actual_seed, "x25519_pub": x_pub, "ed25519_pub": ed_pub}

	@staticmethod
	def sign_notary(private_seed: bytes, data: bytes) -> bytes:
		"""Signs data using the unified identity seed (Ed25519)."""
		priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_seed)
		return priv_key.sign(data)

	@staticmethod
	def verify_notary(public_key_bytes: bytes, data: bytes, signature: bytes) -> bool:
		"""Verifies an Ed25519 signature."""
		try:
			pub_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)
			pub_key.verify(signature, data)
			return True
		except Exception:
			return False

	@staticmethod
	def derive_shared_secret_dh(private_key_bytes: bytes, remote_public_key_bytes: bytes) -> bytes:
		"""Performs X25519 Diffie-Hellman to derive a shared secret."""
		private_key = x25519.X25519PrivateKey.from_private_bytes(private_key_bytes)
		public_key = x25519.X25519PublicKey.from_public_bytes(remote_public_key_bytes)
		return private_key.exchange(public_key)

	@staticmethod
	def _derive_key(shared_secret: Union[str, bytes], salt: bytes = b"red_pill_swarm_v1") -> bytes:
		"""
		Derives a strong 256-bit AES key from a shared secret (string or bytes).
		"""
		hkdf = HKDF(
			algorithm=hashes.SHA256(),
			length=32,
			salt=salt,
			info=b"swarm_e2e_encryption",
		)
		if isinstance(shared_secret, str):
			shared_secret_bytes = shared_secret.encode("utf-8")
		else:
			shared_secret_bytes = shared_secret

		return hkdf.derive(shared_secret_bytes)

	@staticmethod
	def encrypt_payload(payload: dict, shared_secret: Union[str, bytes], nonce: Optional[bytes] = None) -> dict:
		"""
		Encrypts a JSON dictionary payload using AES-GCM.
		Returns a dictionary containing the ciphertext and nonce (IV), Base64 encoded.
		"""
		key = SwarmCrypto._derive_key(shared_secret)
		aesgcm = AESGCM(key)

		# 96-bit nonce is standard for AES-GCM
		used_nonce = nonce if nonce else os.urandom(12)

		payload_bytes = json.dumps(payload).encode("utf-8")
		ciphertext = aesgcm.encrypt(used_nonce, payload_bytes, None)

		return {
			"v": "3.0",  # version updated
			"nonce": base64.b64encode(used_nonce).decode("utf-8"),
			"ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
		}

	@staticmethod
	def decrypt_payload(encrypted_package: dict, shared_secret: Union[str, bytes]) -> dict:
		"""
		Decrypts an E2E encrypted payload back into a JSON dictionary.
		Raises an exception if authentication fails or decryption is invalid.
		"""
		try:
			key = SwarmCrypto._derive_key(shared_secret)
			aesgcm = AESGCM(key)

			nonce = base64.b64decode(encrypted_package["nonce"])
			ciphertext = base64.b64decode(encrypted_package["ciphertext"])

			decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
			result = json.loads(decrypted_bytes.decode("utf-8"))
			if not isinstance(result, dict):
				raise ValueError("Decrypted payload is not a dictionary")
			return result

		except Exception as e:
			raise ValueError(f"Failed to decrypt Swarm Payload. Invalid bond or corrupted data: {e}")
