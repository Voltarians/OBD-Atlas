#!/usr/bin/env python3
"""Import pinned GM Global-A community DBC sources into Atlas.

The imported definitions remain reference evidence. They do not change the
confirmed/candidate status of Atlas's independently validated signal catalog.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path

OPENDBC_COMMIT = "954217059383e0129c650740f11be74cb286000a"
RAW_ROOT = f"https://raw.githubusercontent.com/commaai/opendbc/{OPENDBC_COMMIT}/"

SOURCES = {
    "gm-global-a-hv": "opendbc/dbc/gm_global_a_high_voltage_management.dbc",
    "gm-global-a-lowspeed": "opendbc/dbc/gm_global_a_lowspeed.dbc",
    "gm-global-a-chassis": "opendbc/dbc/gm_global_a_chassis.dbc",
    "gm-global-a-object": "opendbc/dbc/gm_global_a_object.dbc",
    "gm-global-a-powertrain-expansion": "opendbc/dbc/gm_global_a_powertrain_expansion.dbc",
    "gm-global-a-powertrain": "opendbc/dbc/generator/gm/gm_global_a_powertrain.dbc",
}


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "OBD-Atlas/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        destination.write_bytes(response.read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("obd_atlas.sqlite3"))
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "obd-atlas" / "opendbc" / OPENDBC_COMMIT,
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCES),
        help="Import only a selected source; repeat for more than one. Default: all.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    atlas_cli = repo_root / "atlas.py"
    selected = args.source or list(SOURCES)

    for source_name in selected:
        relative_path = SOURCES[source_name]
        local_path = args.cache_dir / Path(relative_path).name
        if not local_path.exists():
            url = RAW_ROOT + relative_path
            print(f"Downloading {source_name}: {url}")
            download(url, local_path)
        else:
            print(f"Using cached {source_name}: {local_path}")

        command = [
            sys.executable,
            str(atlas_cli),
            "dbc-import",
            str(local_path),
            "--database",
            str(args.database),
            "--name",
            f"opendbc-{source_name}-{OPENDBC_COMMIT[:12]}",
            "--replace",
        ]
        subprocess.run(command, cwd=repo_root, check=True)

    print("Imported community DBC sources as provenance-tracked reference evidence.")
    print("Atlas confirmed/candidate signal confidence was not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
