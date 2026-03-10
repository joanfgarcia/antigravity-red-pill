from crypto import SwarmCrypto


def test_encryption():
	shared_secret_bond = "nova_david_770_bond_secret"
	payload = {"intent": "code_review", "sender": "Nova@David", "target": "Aleph@Joan", "data": {"file": "main.py", "diff": "+ print('hello swarm')"}}

	print("--- Original Payload ---")
	print(payload)

	# Encrypt
	encrypted_pkg = SwarmCrypto.encrypt_payload(payload, shared_secret_bond)
	print("\n--- Encrypted Payload (To Firebase) ---")
	print(encrypted_pkg)

	# Decrypt
	decrypted_pkg = SwarmCrypto.decrypt_payload(encrypted_pkg, shared_secret_bond)
	print("\n--- Decrypted Payload (At Receiver) ---")
	print(decrypted_pkg)

	assert payload == decrypted_pkg
	print("\nSUCCESS: E2E Encryption and Decryption match perfectly.")


if __name__ == "__main__":
	test_encryption()
