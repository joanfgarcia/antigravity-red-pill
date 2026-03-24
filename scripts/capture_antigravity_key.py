#!/usr/bin/env python3
"""
Hook al inspector V8/Node.js de Antigravity via Chrome DevTools Protocol (v3).
Robust against missing 'require' in renderer/worker contexts.
"""

import asyncio
import json
import urllib.request

import websockets

HOOK_JS = """
(function() {
	let keysFound = new Set();
	let r = null;

	try {
		if (typeof require !== 'undefined') {
			r = require;
		} else if (typeof process !== 'undefined' && process.mainModule && typeof process.mainModule.require === 'function') {
			r = process.mainModule.require;
		}
	} catch(e) {}

	if (!r) {
		console.log('HOOK_FAIL: require is not available');
		return 'FAIL_NO_REQUIRE';
	}

	// HOOK 1: crypto.createCipheriv
	try {
		const crypto = r('crypto');
		const origCipheriv = crypto.createCipheriv.bind(crypto);
		crypto.createCipheriv = function(algo, key, iv) {
			if (algo && algo.toLowerCase().includes('aes')) {
				const keyHex = Buffer.from(key).toString('hex');
				const keyB64 = Buffer.from(key).toString('base64');
				const ivH = iv ? Buffer.from(iv).toString('hex') : 'null';
				if (!keysFound.has(keyHex)) {
					keysFound.add(keyHex);
					console.log('KEY_CAPTURED algo=' + algo + ' KEY_HEX=' + keyHex + ' KEY_B64=' + keyB64 + ' IV=' + ivH);
				}
			}
			return origCipheriv(algo, key, iv);
		};
		console.log('HOOK1_OK crypto.createCipheriv hooked');
	} catch(e) {
		console.log('HOOK1_FAIL ' + e.message);
	}

	// HOOK 2: createDecipheriv
	try {
		const crypto = r('crypto');
		const origDecipheriv = crypto.createDecipheriv.bind(crypto);
		crypto.createDecipheriv = function(algo, key, iv) {
			if (algo && algo.toLowerCase().includes('aes')) {
				const keyHex = Buffer.from(key).toString('hex');
				const keyB64 = Buffer.from(key).toString('base64');
				const ivH = iv ? Buffer.from(iv).toString('hex') : 'null';
				if (!keysFound.has(keyHex)) {
					keysFound.add(keyHex);
					console.log('KEY_CAPTURED_DEC algo=' + algo + ' KEY_HEX=' + keyHex + ' KEY_B64=' + keyB64 + ' IV=' + ivH);
				}
			}
			return origDecipheriv(algo, key, iv);
		};
		console.log('HOOK2_OK crypto.createDecipheriv hooked');
	} catch(e) {
		console.log('HOOK2_FAIL ' + e.message);
	}

	// HOOK 3: electron safeStorage
	try {
		const { safeStorage } = r('electron');
		if (safeStorage) {
			const origDecrypt = safeStorage.decryptString.bind(safeStorage);
			safeStorage.decryptString = function(buf) {
				const result = origDecrypt(buf);
				console.log('SAFE_STORAGE_DECRYPT len=' + result.length + ' preview=' + result.substring(0, 80).replace(/\\n/g, '\\\\n'));
				return result;
			};
			console.log('HOOK3_OK safeStorage.decryptString hooked');
		}
	} catch(e) {
		console.log('HOOK3_FAIL ' + e.message);
	}

	return 'ALL_HOOKS_INSTALLED';
})();
"""


async def hook_target(ws_url: str, label: str):
	print(f"[*] Connecting to {label}: {ws_url[:70]}")
	try:
		async with websockets.connect(ws_url, ping_interval=None, open_timeout=5) as ws:
			for method in ["Runtime.enable", "Console.enable"]:
				await ws.send(json.dumps({"id": 1, "method": method}))
				await asyncio.wait_for(ws.recv(), timeout=3)

			await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": HOOK_JS, "returnByValue": True}}))
			r = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
			val = r.get("result", {}).get("result", {}).get("value", "N/A")
			print(f"[*] Hook result in {label}: {val}")

			while True:
				try:
					msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
					data = json.loads(msg)
					method = data.get("method", "")
					if method == "Runtime.consoleAPICalled":
						args = data.get("params", {}).get("args", [])
						text = " ".join(str(a.get("value", a.get("description", ""))) for a in args)
						if any(k in text for k in ["KEY_CAPTURED", "HOOK", "SAFE_STORAGE"]):
							print(f"\n[CAPTURED:{label}] {text}")
				except asyncio.TimeoutError:
					continue
				except Exception as e:
					print(f"\n[ERR:{label}] {e}")
					break
	except Exception as e:
		print(f"[!] {label} Error: {e}")


async def main():
	try:
		req = urllib.request.Request("http://127.0.0.1:9229/json")
		with urllib.request.urlopen(req, timeout=5) as r:
			targets = json.loads(r.read())
	except Exception as e:
		print(f"[!] Error fetching targets: {e}")
		return

	print(f"[*] Found {len(targets)} targets. Hooking...")
	tasks = []
	for t in targets:
		ws_url = t.get("webSocketDebuggerUrl", "")
		if ws_url:
			tasks.append(hook_target(ws_url, t.get("title", "unknown")))

	if tasks:
		await asyncio.gather(*tasks)


if __name__ == "__main__":
	asyncio.run(main())
