import base64
import json
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

class SwarmCrypto:
	"""
	Handles End-to-End Encryption (E2E) for Swarm Messaging payloads.
	Uses AES-GCM for authenticated encryption.
	The encryption key is derived from the shared True Name Bond (Shared Secret).
	"""

	@staticmethod
	def _derive_key(shared_secret: str, salt: bytes = b"red_pill_swarm_v1") -> bytes:
		"""
		Derives a strong 256-bit AES key from the human-agent bond string.
		"""
		hkdf = HKDF(
			algorithm=hashes.SHA256(),
			length=32,
			salt=salt,
			info=b"swarm_e2e_encryption",
		)
		return hkdf.derive(shared_secret.encode('utf-8'))

	@staticmethod
	def encrypt_payload(payload: dict, shared_secret: str) -> dict:
		"""
		Encrypts a JSON dictionary payload using AES-GCM.
		Returns a dictionary containing the ciphertext and nonce (IV), Base64 encoded.
		"""
		key = SwarmCrypto._derive_key(shared_secret)
		aesgcm = AESGCM(key)
		
		# 96-bit nonce is standard for AES-GCM
		nonce = os.urandom(12) 
		
		payload_bytes = json.dumps(payload).encode('utf-8')
		ciphertext = aesgcm.encrypt(nonce, payload_bytes, None)
		
		return {
			"v": 1, # version
			"nonce": base64.b64encode(nonce).decode('utf-8'),
			"ciphertext": base64.b64encode(ciphertext).decode('utf-8')
		}

	@staticmethod
	def decrypt_payload(encrypted_package: dict, shared_secret: str) -> dict:
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
			return json.loads(decrypted_bytes.decode('utf-8'))
			
		except Exception as e:
			raise ValueError(f"Failed to decrypt Swarm Payload. Invalid bond or corrupted data: {e}")

