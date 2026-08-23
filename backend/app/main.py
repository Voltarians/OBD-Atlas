from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

DATA_ROOT = Path(os.getenv("OBD_ATLAS_DATA", "/data/captures"))
API_KEY = os.getenv("OBD_ATLAS_API_KEY", "")
MAX_BYTES = int(os.getenv("OBD_ATLAS_MAX_UPLOAD_BYTES", "268435456"))

app = FastAPI(title="OBD Atlas Receiver", version="0.1.0")


def safe_slug(value: Any) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return result or "unknown"


def vehicle_partition(metadata: dict[str, Any]) -> str:
    identity = metadata.get("vehicleIdentity")
    if not isinstance(identity, dict):
        raise HTTPException(status_code=422, detail="vehicleIdentity is required")
    if identity.get("vin"):
        raise HTTPException(
            status_code=422,
            detail="raw VIN must not be uploaded; send a keyed vinHash",
        )
    confirmed = identity.get("status") == "operatorConfirmed"
    required = ("vinHash", "make", "model", "modelYear", "operatorConfirmedUtc")
    if confirmed and all(identity.get(field) for field in required):
        year = identity["modelYear"]
        if not isinstance(year, int) or year < 1886 or year > 2200:
            raise HTTPException(status_code=422, detail="invalid modelYear")
        return "/".join(
            (safe_slug(identity["make"]), safe_slug(identity["model"]), str(year)),
        )
    identity["status"] = "unclassified"
    identity.pop("operatorConfirmedUtc", None)
    return "UNCLASSIFIED"


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "obd-atlas-receiver"}


@app.post("/v1/captures", status_code=201)
async def create_capture(
    manifest: str = Form(...),
    bundle: UploadFile = File(...),
    x_obd_atlas_key: str | None = Header(default=None),
) -> dict[str, str | int]:
    if not API_KEY or x_obd_atlas_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")
    try:
        metadata: dict[str, Any] = json.loads(manifest)
    except (json.JSONDecodeError, TypeError) as error:
        raise HTTPException(status_code=400, detail="invalid manifest JSON") from error
    if metadata.get("operatorApprovedUpload") is not True:
        raise HTTPException(status_code=422, detail="operator upload consent required")

    partition = vehicle_partition(metadata)
    capture_id = str(uuid.uuid4())
    captured = bytearray()
    while chunk := await bundle.read(1024 * 1024):
        captured.extend(chunk)
        if len(captured) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="capture bundle too large")

    now = datetime.now(timezone.utc)
    directory = DATA_ROOT / partition / f"{now:%Y/%m/%d}" / capture_id
    directory.mkdir(parents=True, exist_ok=False)
    payload_path = directory / "capture.bundle"
    payload_path.write_bytes(captured)
    digest = hashlib.sha256(captured).hexdigest()
    record = {
        "captureId": capture_id,
        "receivedUtc": now.isoformat(),
        "storagePartition": partition,
        "sha256": digest,
        "bytes": len(captured),
        "manifest": metadata,
    }
    (directory / "record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {
        "captureId": capture_id,
        "storagePartition": partition,
        "sha256": digest,
        "bytes": len(captured),
    }
