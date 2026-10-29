#!/usr/bin/env python3
"""Lee la cabecera GGUF sin llama.cpp: valida integridad y saca la ctx declarada por el modelo."""
import struct, sys, json

FMT = {0:"B",1:"b",2:"H",3:"h",4:"I",5:"i",6:"f",7:"?",10:"Q",11:"q",12:"d"}
SZ = {0:1,1:1,2:2,3:2,4:4,5:4,6:4,7:1,10:8,11:8,12:8}

def rd(f, t):
	if t == 8:
		n = struct.unpack("<Q", f.read(8))[0]
		return f.read(n).decode("utf-8", "replace")
	if t == 9:
		et = struct.unpack("<I", f.read(4))[0]
		n = struct.unpack("<Q", f.read(8))[0]
		return [rd(f, et) for _ in range(n)]
	return struct.unpack("<" + FMT[t], f.read(SZ[t]))[0]

path = sys.argv[1]
with open(path, "rb") as f:
	magic = f.read(4)
	if magic != b"GGUF":
		sys.exit(f"NO es GGUF: {magic!r}")
	ver = struct.unpack("<I", f.read(4))[0]
	n_tensors = struct.unpack("<Q", f.read(8))[0]
	n_kv = struct.unpack("<Q", f.read(8))[0]
	meta = {}
	for _ in range(n_kv):
		k = rd(f, 8)
		t = struct.unpack("<I", f.read(4))[0]
		v = rd(f, t)
		meta[k] = v
	print(f"GGUF v{ver} | tensores={n_tensors} | kv={n_kv}")
	keys = ["general.architecture", "general.name", "general.parameter_count",
	        "general.file_type"]
	for k in keys:
		if k in meta: print(f"  {k} = {meta[k]}")
	print("  --- contexto / arquitectura ---")
	for k in sorted(meta):
		if any(s in k for s in ("context_length", "block_count", "head_count",
		                        "embedding_length", "rope.freq", "expert_count",
		                        "feed_forward_length")):
			print(f"  {k} = {meta[k]}")
	print("  --- tokenizer ---")
	for k in ("tokenizer.ggml.model", "tokenizer.ggml.tokens", "tokenizer.ggml.merges"):
		if k in meta and isinstance(meta[k], list):
			print(f"  {k} = <list len={len(meta[k])}>")
