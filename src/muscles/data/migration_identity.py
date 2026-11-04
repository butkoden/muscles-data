"""Stable storage keys shared by compatible migration journals."""
import hashlib
import json


def migration_identity(source: str, version: str) -> str:
    if not source or not version:
        raise ValueError("Source and version are required")
    return hashlib.sha256(json.dumps([source, version], ensure_ascii=False).encode()).hexdigest()
