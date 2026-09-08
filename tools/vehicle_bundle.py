"""Validate and stage raw capture bundles without trusting their metadata."""
from __future__ import annotations
import hashlib
import json
import re
import shutil
from pathlib import Path
from .vehicle_catalog import IntakeError, Vehicle, canonical_vehicle, slug

SCHEMA = 'voltec-atlas.capture-session.v1'
PUBLIC_TYPES = frozenset({'chevrolet-volt-gen1', 'chevrolet-volt-gen2'})
SAFE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$')
MAX_FILE = 2 * 1024**3

def safe_name(value):
    reserved = {'receipt.json','original.session.json','reviewed.session.json'}
    if not isinstance(value, str) or not SAFE.fullmatch(value) or value in ('.','..') or value.lower() in reserved:
        raise IntakeError('Unsafe file or session name.')
    if value.split('.')[0].upper() in {'CON','PRN','AUX','NUL','COM1','COM2','LPT1','LPT2'}:
        raise IntakeError('Reserved filename.')
    return value

def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()

def write_json(path, data):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    tmp.replace(path)

def load_bundle(path):
    if path.is_symlink(): raise IntakeError('Symlink manifest rejected.')
    path = path.resolve(strict=True)
    raw = path.read_bytes()
    if len(raw) > 2_000_000: raise IntakeError('Manifest exceeds size limit.')
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA:
        raise IntakeError('Unsupported manifest schema.')
    safe_name(manifest.get('session_id'))
    entries = manifest.get('files')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise IntakeError('Invalid file list.')
    files, names, roles, total = [], set(), set(), 0
    digest = hashlib.sha256(raw)
    for entry in entries:
        if not isinstance(entry, dict): raise IntakeError('Invalid file entry.')
        name, role = safe_name(entry.get('name')), safe_name(entry.get('role'))
        if name in names or role in roles: raise IntakeError('Duplicate file or role.')
        names.add(name); roles.add(role)
        source = path.parent / name
        if source.is_symlink() or not source.is_file(): raise IntakeError('Missing or unsafe capture file.')
        size = source.stat().st_size
        total += size
        if size > MAX_FILE or total > 8*1024**3: raise IntakeError('Bundle exceeds size limit.')
        actual = sha256_file(source)
        expected = entry.get('sha256')
        if entry.get('size_bytes') is not None and entry['size_bytes'] != size:
            raise IntakeError('File size mismatch.')
        if expected is not None and (not isinstance(expected,str) or not re.fullmatch('[0-9a-fA-F]{64}',expected) or expected.lower()!=actual):
            raise IntakeError('SHA-256 mismatch.')
        digest.update(name.encode()); digest.update(bytes.fromhex(actual))
        files.append((name, role, source, size, actual))
    if 'candump_log' not in roles: raise IntakeError('Missing candump_log.')
    return manifest, files, digest.hexdigest()

def stage(manifest_path, root, scope='public'):
    if scope not in ('public','research'): raise IntakeError('Invalid intake scope.')
    manifest, files, fingerprint = load_bundle(manifest_path)
    candidate = canonical_vehicle(manifest.get('vehicle', {}))
    if scope == 'public' and candidate.known and candidate.vehicle_type not in PUBLIC_TYPES:
        raise IntakeError('Public intake accepts Chevrolet Volt only.')
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root/'incoming'/f"{safe_name(manifest['session_id'])}-{fingerprint[:16]}"
    if destination.exists():
        receipt = json.loads((destination/'receipt.json').read_text())
        if receipt.get('fingerprint') == fingerprint: return destination
        raise IntakeError('Conflicting submission.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name+'.partial')
    if temporary.exists(): raise IntakeError('Partial submission exists.')
    temporary.mkdir(mode=0o700)
    try:
        copied=[]
        for name,role,source,size,digest in files:
            target=temporary/name
            shutil.copyfile(source,target)
            if sha256_file(target)!=digest: raise IntakeError('Copy verification failed.')
            copied.append(dict(name=name,role=role,size_bytes=size,sha256=digest))
        shutil.copyfile(manifest_path, temporary/'original.session.json')
        write_json(temporary/'receipt.json',dict(
            schema='obd-atlas.intake-receipt.v1',fingerprint=fingerprint,
            session_id=manifest['session_id'],scope=scope,state='awaiting_identity_review',
            candidate=candidate.as_dict(),files=copied,
            original_manifest_sha256=sha256_file(temporary/'original.session.json'),
            identity_review_required=True,privacy_review_required=True))
        temporary.rename(destination)
    except BaseException:
        shutil.rmtree(temporary,ignore_errors=True)
        raise
    return destination
