#!/usr/bin/env python3
"""Private, review-gated OBD Atlas intake. No network listener."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.vehicle_catalog import IntakeError, Vehicle, canonical_vehicle
from tools.vehicle_bundle import SCHEMA, PUBLIC_TYPES, safe_name, sha256_file, write_json, stage

def review(staged, root, vehicle, evidence, *, privacy_reviewed=False,
           import_database=True, reclassify_research=False):
    root=root.expanduser().resolve()
    staged=staged.expanduser().resolve(strict=True)
    if staged.parent != (root/'incoming').resolve(): raise IntakeError('Invalid staging directory.')
    receipt=json.loads((staged/'receipt.json').read_text())
    if receipt.get('state')!='awaiting_identity_review': raise IntakeError('Not awaiting review.')
    if not evidence.strip() or not privacy_reviewed or not vehicle.known:
        raise IntakeError('Independent identity evidence and explicit privacy review are required.')
    if receipt['scope']=='public' and vehicle.vehicle_type not in PUBLIC_TYPES:
        if not reclassify_research: raise IntakeError('Public intake is Volt-only.')
        receipt['scope']='research'
    candidate=canonical_vehicle(receipt['candidate'])
    if candidate.known and candidate!=vehicle: raise IntakeError('Conflicting identity.')
    for entry in receipt['files']:
        path=staged/safe_name(entry['name'])
        if path.is_symlink() or sha256_file(path)!=entry['sha256']:
            raise IntakeError('Staged file changed.')
    original=staged/'original.session.json'
    if original.is_symlink() or sha256_file(original)!=receipt['original_manifest_sha256']:
        raise IntakeError('Original manifest changed.')
    manifest=json.loads(original.read_text())
    declared=canonical_vehicle(manifest.get('vehicle',{}))
    if declared.known and declared!=vehicle: raise IntakeError('Original identity conflicts.')
    clean=dict(schema=SCHEMA,session_id=receipt['session_id'],
        capture_type=safe_name(manifest['capture_type']),
        vehicle={**vehicle.as_dict(),'identity_source':'curator_verified','identity_status':'verified'},
        files=[{**entry,'format':'candump_-L' if entry['role']=='candump_log' else 'unknown'} for entry in receipt['files']],
        buses=[],time={key:manifest.get('time',{}).get(key) for key in (
            'metadata_started_utc','first_can_frame_utc','last_can_frame_utc',
            'can_duration_seconds','audio_duration_seconds')},
        capture_status=dict(total_frames=int(manifest.get('capture_status',{}).get('total_frames',0)),
                            complete_shutdown=bool(manifest.get('capture_status',{}).get('complete_shutdown',False)),
                            termination_reason='reviewed_capture'),
        ingestion=dict(retain_original_interface_names=True,public_upload_authorized=False),host=None)
    for bus in manifest.get('buses',[]):
        bitrate=bus.get('bitrate')
        if bitrate is not None and (not isinstance(bitrate,int) or isinstance(bitrate,bool) or not 1<=bitrate<=10000000):
            raise IntakeError('Invalid bitrate.')
        clean['buses'].append(dict(logged_interface=safe_name(bus['logged_interface']),
            atlas_bus='unassigned',bitrate=bitrate,mode='passive_capture',
            frames=int(bus.get('frames',0)),unique_arbitration_ids=int(bus.get('unique_arbitration_ids',0)),
            captured=bool(bus.get('captured',True))))
    clean_path=staged/'reviewed.session.json'
    write_json(clean_path,clean)
    destination=root/'vehicles'/vehicle.vehicle_type/vehicle.year_key/staged.name
    if destination.exists(): raise IntakeError('Destination already exists.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if import_database:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        import atlas
        database=root/'databases'/f'{vehicle.vehicle_type}.sqlite3'
        args=argparse.Namespace(manifest=clean_path,database=database,source_dir=staged,
                                replace=False,skip_hash_check=False)
        try: atlas.ingest(args)
        except Exception as exc: raise IntakeError(f'Database import failed: {exc}') from exc
    receipt.update(state='accepted_private',verified_vehicle=vehicle.as_dict(),
                   identity_evidence=evidence,privacy_reviewed=True)
    write_json(staged/'receipt.json',receipt)
    staged.rename(destination)
    return destination

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    intake=sub.add_parser('ingest'); intake.add_argument('manifest',type=Path)
    intake.add_argument('--root',type=Path,required=True)
    intake.add_argument('--scope',choices=('public','research'),default='public')
    approve=sub.add_parser('review'); approve.add_argument('staged',type=Path)
    approve.add_argument('--root',type=Path,required=True)
    approve.add_argument('--make',required=True); approve.add_argument('--model',required=True)
    approve.add_argument('--year',type=int,required=True); approve.add_argument('--generation',type=int)
    approve.add_argument('--evidence',required=True); approve.add_argument('--privacy-reviewed',action='store_true')
    approve.add_argument('--reclassify-research',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command=='ingest': path=stage(args.manifest,args.root,args.scope)
        else:
            vehicle=canonical_vehicle(dict(make=args.make,model=args.model,model_year=args.year,
                                           generation=args.generation),allow_unknown=False)
            path=review(args.staged,args.root,vehicle,args.evidence,privacy_reviewed=args.privacy_reviewed,
                        reclassify_research=args.reclassify_research)
        print(path); return 0
    except (IntakeError,OSError) as exc:
        print(f'Atlas intake error: {exc}',file=sys.stderr); return 2

if __name__=='__main__':
    raise SystemExit(main())
