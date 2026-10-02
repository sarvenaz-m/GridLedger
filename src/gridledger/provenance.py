"""Portable SHA-256 attestations. A local hash chain is not a blockchain."""
from __future__ import annotations
import hashlib
import json
from typing import Any


def canonical(value: Any) -> bytes:
    """Application encoding: sorted keys, compact UTF-8, no floats in attestations.

    Schema payloads use ASCII strings, integers and booleans for JS/Python parity.
    This is an application-specific encoding, not a claim of RFC 8785 compliance.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def append(chain: list[dict], payload: dict) -> dict:
    body = {"index": len(chain), "previous": chain[-1]["hash"] if chain else "0" * 64, "payload": payload}
    record = {**body, "hash": digest(body)}
    chain.append(record)
    return record


def verify(chain: list[dict], expected_head: str | None = None) -> tuple[bool, str]:
    previous = "0" * 64
    for i, record in enumerate(chain):
        if not isinstance(record, dict) or set(record) != {"index", "previous", "payload", "hash"}:
            return False, f"Invalid record schema at {i}"
        if record["index"] != i or record["previous"] != previous:
            return False, f"Broken ordering or link at {i}"
        body = {k: record[k] for k in ("index", "previous", "payload")}
        if digest(body) != record["hash"]:
            return False, f"Payload digest mismatch at {i}"
        previous = record["hash"]
    if expected_head is not None and previous != expected_head:
        return False, "Head differs from the trusted checkpoint"
    return True, "Verified against checkpoint" if expected_head else "Internally consistent; no external checkpoint"
