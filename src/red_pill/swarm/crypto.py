import base64
import json
import os
from typing import Dict, List, Optional, Tuple, Union

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class SwarmCrypto:
	"""
	Handles End-to-End Encryption (E2E) for Swarm Messaging payloads.
	v2.0: Supports Asymmetric X25519 (Diffie-Hellman) and AES-GCM for Perfect Forward Secrecy logic.
	The encryption key can be derived from the shared True Name Bond or via Asymmetric DH.
	"""

	@staticmethod
	def generate_x25519_keypair() -> Tuple[bytes, bytes]:
		"""Generates an X25519 private/public key pair (bytes)."""
		private_key = x25519.X25519PrivateKey.generate()
		public_key = private_key.public_key()
		
		priv_bytes = private_key.private_bytes(
			encoding=serialization.Encoding.Raw,
			format=serialization.PrivateFormat.Raw,
			encryption_algorithm=serialization.NoEncryption()
		)
		pub_bytes = public_key.public_bytes(
			encoding=serialization.Encoding.Raw,
			format=serialization.PublicFormat.Raw
		)
		return priv_bytes, pub_bytes

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
			"v": 2,  # version updated
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

	# MLS / TreeKEM Primitives (v3.0 - Research Build)
	
	@staticmethod
	def generate_treekem_leaf() -> Dict[str, bytes]:
		"""Generates a leaf node for an MLS tree (Private Key + Public Key)."""
		priv, pub = SwarmCrypto.generate_x25519_keypair()
		return {"private": priv, "public": pub}

	@staticmethod
	def combine_nodes(left_node_pub: bytes, right_node_pub: bytes) -> bytes:
		"""
		Conceptual 'Node Parent' derivation for TreeKEM.
		In real MLS, this calculates a hash of secrets, but here we derive 
		a reproducible 'middle point' or composite key for the parent node.
		"""
		hasher = hashes.Hash(hashes.SHA256())
		hasher.update(left_node_pub)
		hasher.update(right_node_pub)
		return hasher.finalize()

	@staticmethod
	def derive_group_key(secrets: List[bytes]) -> bytes:
		"""
		Derives a final Group Encryption Key from the root of the TreeKEM tree.
		"""
		hkdf = HKDF(
			algorithm=hashes.SHA256(),
			length=32,
			salt=b"red_pill_mls_group_v1",
			info=b"mls_group_key_derivation",
		)
		# Combine all secrets into a single entropy pool
		pool = b"".join(secrets)
		return hkdf.derive(pool)
