#!/usr/bin/env python3
"""OBD Atlas J2534 JSONL trace writer/parser.

This module is transport-agnostic. It does not load a J2534 DLL, open an
interface, or communicate with a vehicle. A future PassThru proxy can call the
writer around forwarded API calls while preserving the vendor DLL behavior.

SecurityAccess (0x27) and TransferData (0x36) message payloads are redacted by
default. Their byte length and SHA-256 digest are retained for reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

SCHEMA_ID = "obd-atlas.j2534-trace.v1"
SENSITIVE_SERVICES = {
    0x27: "SecurityAccess",
    0x36: "TransferData",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def provider_fingerprint(provider: Mapping[str, Any]) -> str:
    """Stable SHA-256 over the provider identity recorded by inventory."""
    identity = {
        "registryPath": provider.get("registryPath"),
        "registrySubkey": provider.get("registrySubkey"),
        "name": provider.get("name"),
        "vendor": provider.get("vendor"),
        "functionLibrary": provider.get("functionLibrary"),
    }
    return hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


def _payload_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        compact = "".join(value.split())
        if compact.lower().startswith("0x"):
            compact = compact[2:]
        return bytes.fromhex(compact) if compact else b""
    if isinstance(value, Iterable):
        return bytes(int(item) & 0xFF for item in value)
    raise TypeError(f"unsupported payload type: {type(value)!r}")


def sanitize_message(
    message: Mapping[str, Any],
    *,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    """Normalize one J2534 message without mutating the caller's object.

    The future proxy should provide `service` when it has decoded enough of the
    ISO-TP/GM request to identify the diagnostic service. This keeps redaction
    explicit instead of guessing through arbitrary raw transport bytes.
    """
    payload = _payload_bytes(message.get("data", message.get("payloadHex")))
    service_value = message.get("service")
    if isinstance(service_value, str):
        service = int(service_value, 0)
    elif service_value is None:
        service = None
    else:
        service = int(service_value)

    row: dict[str, Any] = {
        key: value
        for key, value in message.items()
        if key not in {"data", "payloadHex"}
    }
    row["dataLength"] = len(payload)

    sensitive_name = SENSITIVE_SERVICES.get(service) if service is not None else None
    if sensitive_name and not include_sensitive:
        row["payloadRedacted"] = True
        row["payloadSha256"] = hashlib.sha256(payload).hexdigest()
        row["sensitiveService"] = sensitive_name
    else:
        row["payloadRedacted"] = False
        row["payloadHex"] = payload.hex().upper()
    return row


def sanitize_messages(
    messages: Iterable[Mapping[str, Any]],
    *,
    include_sensitive: bool = False,
) -> list[dict[str, Any]]:
    return [
        sanitize_message(message, include_sensitive=include_sensitive)
        for message in messages
    ]


class J2534TraceWriter:
    """Append-only JSONL trace writer for a future transparent J2534 proxy."""

    def __init__(
        self,
        path: Path | str,
        *,
        provider: Mapping[str, Any],
        source_application: str,
        source_application_version: str | None = None,
        include_sensitive_payloads: bool = False,
        utc_clock: Callable[[], str] = utc_now_iso,
        monotonic_clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.provider = dict(provider)
        self.source_application = source_application
        self.source_application_version = source_application_version
        self.include_sensitive_payloads = include_sensitive_payloads
        self._utc_clock = utc_clock
        self._monotonic_clock_ns = monotonic_clock_ns
        self._sequence = 0
        self._call_sequence = 0
        self._open_calls: dict[str, dict[str, Any]] = {}
        self._handle = self.path.open("x", encoding="utf-8", newline="\n")
        self._write_session()

    def __enter__(self) -> "J2534TraceWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.flush()
            self._handle.close()

    def _base_record(self, record_type: str) -> dict[str, Any]:
        row = {
            "schema": SCHEMA_ID,
            "recordType": record_type,
            "sequence": self._sequence,
            "utc": self._utc_clock(),
            "monotonicNs": int(self._monotonic_clock_ns()),
        }
        self._sequence += 1
        return row

    def _write(self, row: Mapping[str, Any]) -> None:
        self._handle.write(_canonical_json(dict(row)) + "\n")
        self._handle.flush()

    def _write_session(self) -> None:
        row = self._base_record("session")
        row.update(
            {
                "observerMode": "transparent-forwarder",
                "proxyMayTransmitIndependently": False,
                "sourceApplication": self.source_application,
                "sourceApplicationVersion": self.source_application_version,
                "processId": os.getpid(),
                "provider": self.provider,
                "providerFingerprintSha256": provider_fingerprint(self.provider),
                "sensitivePayloadPolicy": (
                    "included" if self.include_sensitive_payloads else "redact-security-access-and-transfer-data"
                ),
            }
        )
        self._write(row)

    def begin_call(
        self,
        api: str,
        *,
        arguments: Mapping[str, Any] | None = None,
        device_id: int | None = None,
        channel_id: int | None = None,
        thread_id: int | None = None,
        messages: Iterable[Mapping[str, Any]] | None = None,
    ) -> str:
        self._call_sequence += 1
        call_id = f"call-{self._call_sequence:08d}"
        row = self._base_record("callBegin")
        row.update(
            {
                "callId": call_id,
                "api": api,
                "threadId": thread_id if thread_id is not None else threading.get_ident(),
                "deviceId": device_id,
                "channelId": channel_id,
                "arguments": dict(arguments or {}),
            }
        )
        if messages is not None:
            row["messages"] = sanitize_messages(
                messages,
                include_sensitive=self.include_sensitive_payloads,
            )
        self._open_calls[call_id] = {
            "api": api,
            "startedMonotonicNs": row["monotonicNs"],
        }
        self._write(row)
        return call_id

    def end_call(
        self,
        call_id: str,
        *,
        return_code: int,
        outputs: Mapping[str, Any] | None = None,
        messages: Iterable[Mapping[str, Any]] | None = None,
        error_text: str | None = None,
    ) -> None:
        started = self._open_calls.pop(call_id, None)
        if started is None:
            raise ValueError(f"unknown or already-ended call id: {call_id}")
        row = self._base_record("callEnd")
        row.update(
            {
                "callId": call_id,
                "api": started["api"],
                "returnCode": int(return_code),
                "durationNs": int(row["monotonicNs"]) - int(started["startedMonotonicNs"]),
                "outputs": dict(outputs or {}),
            }
        )
        if messages is not None:
            row["messages"] = sanitize_messages(
                messages,
                include_sensitive=self.include_sensitive_payloads,
            )
        if error_text:
            row["errorText"] = error_text
        self._write(row)


def read_trace(path: Path | str) -> list[dict[str, Any]]:
    """Read and structurally validate a J2534 trace JSONL file."""
    records: list[dict[str, Any]] = []
    open_calls: dict[str, str] = {}
    expected_sequence = 0
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON on line {line_number}: {error}") from error
            if row.get("schema") != SCHEMA_ID:
                raise ValueError(f"unexpected schema on line {line_number}")
            if row.get("sequence") != expected_sequence:
                raise ValueError(
                    f"non-contiguous sequence on line {line_number}: expected {expected_sequence}, got {row.get('sequence')}"
                )
            expected_sequence += 1
            record_type = row.get("recordType")
            if not records and record_type != "session":
                raise ValueError("first trace record must be session")
            if record_type == "callBegin":
                call_id = row.get("callId")
                if not call_id or call_id in open_calls:
                    raise ValueError(f"invalid duplicate callBegin on line {line_number}")
                open_calls[str(call_id)] = str(row.get("api"))
            elif record_type == "callEnd":
                call_id = str(row.get("callId"))
                api = open_calls.pop(call_id, None)
                if api is None:
                    raise ValueError(f"orphan callEnd on line {line_number}")
                if str(row.get("api")) != api:
                    raise ValueError(f"API mismatch for {call_id} on line {line_number}")
            elif record_type != "session":
                raise ValueError(f"unknown recordType {record_type!r} on line {line_number}")
            records.append(row)
    if not records:
        raise ValueError("empty J2534 trace")
    return records


def summarize_trace(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    begins = [row for row in rows if row.get("recordType") == "callBegin"]
    ends = [row for row in rows if row.get("recordType") == "callEnd"]
    message_count = sum(len(row.get("messages") or []) for row in rows)
    redacted_count = sum(
        1
        for row in rows
        for message in (row.get("messages") or [])
        if message.get("payloadRedacted")
    )
    apis: dict[str, int] = {}
    for row in begins:
        api = str(row.get("api"))
        apis[api] = apis.get(api, 0) + 1
    return {
        "schema": SCHEMA_ID,
        "records": len(rows),
        "callsStarted": len(begins),
        "callsCompleted": len(ends),
        "messages": message_count,
        "redactedMessages": redacted_count,
        "apiCounts": dict(sorted(apis.items())),
    }
