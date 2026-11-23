"""Fingerprint raw safetensors payloads without loading or casting weights."""
import hashlib
import json
import mmap
import struct


def tensor_hashes(shards):
    tensors = {}
    for shard in sorted(shards):
        with shard.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
            header_size, = struct.unpack_from("<Q", data)
            start = 8 + header_size
            if not 8 < start <= len(data):
                raise ValueError(f"Invalid safetensors header in {shard.name}")
            header = json.loads(data[8:start])
            for name, record in header.items():
                if name == "__metadata__":
                    continue
                lo, hi = record["data_offsets"]
                if name in tensors or not 0 <= lo <= hi <= len(data) - start:
                    raise ValueError(f"Duplicate or invalid tensor {name}")
                with memoryview(data)[start + lo:start + hi] as payload:
                    tensors[name] = {"dtype": record["dtype"], "shape": record["shape"],
                                     "sha256": hashlib.sha256(payload).hexdigest()}
    return tensors
