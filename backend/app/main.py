from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile

DATA_ROOT = Path(os.getenv("OBD_ATLAS_DATA", "/data/captures"))
API_KEY = os.getenv("OBD_ATLAS_API_KEY", "")
MAX_BYTES = int(os.getenv("OBD_ATLAS_MAX_UPLOAD_BYTES", "268435456"))

app = FastAPI(title="OBD Atlas Receiver", version="0.1.0")


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
        metadata = json.loads(manifest)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="invalid manifest JSON") from error
    if metadata.get("operatorApprovedUpload") is not True:
        raise HTTPException(status_code=422, detail="operator upload consent required")

    capture_id = str(uuid.uuid4())
    captured = bytearray()
    while chunk := await bundle.read(1024 * 1024):
        captured.extend(chunk)
        if len(captured) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="capture bundle too large")

    now = datetime.now(timezone.utc)
    directory = DATA_ROOT / f"{now:%Y/%m/%d}" / capture_id
    directory.mkdir(parents=True, exist_ok=False)
    payload_path = directory / "capture.bundle"
    payload_path.write_bytes(captured)
    digest = hashlib.sha256(captured).hexdigest()
    record = {
        "captureId": capture_id,
        "receivedUtc": now.isoformat(),
        "sha256": digest,
        "bytes": len(captured),
        "manifest": metadata,
    }
    (directory / "record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"captureId": capture_id, "sha256": digest, "bytes": len(captured)}
