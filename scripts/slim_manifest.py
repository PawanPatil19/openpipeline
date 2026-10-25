"""Shrink a dbt ``manifest.json`` to what OpenPipeline reads, for use as a test fixture.

    python scripts/slim_manifest.py target/manifest.json out.json [--gzip]

The output is deterministic (sorted keys, compact separators), so regenerating a
fixture gives a clean diff.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

KEEP_RESOURCE_TYPES = frozenset({"model", "seed", "snapshot", "test"})
KEEP_METADATA = ("dbt_version", "adapter_type")
KEEP_NODE_KEYS = (
    "resource_type",
    "name",
    "unique_id",
    "package_name",
    "description",
    "original_file_path",
    "path",
    "language",
    "raw_code",
    "compiled_code",
    "config",
    "depends_on",
    "columns",
    "tags",
    "meta",
    "column_name",
    "attached_node",
    "test_metadata",
    "fqn",
    "relation_name",
    "alias",
    "schema",
    "database",
)


def slim_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``manifest`` with only the fields OpenPipeline uses."""
    metadata = manifest.get("metadata") or {}
    nodes = {
        uid: {k: node[k] for k in KEEP_NODE_KEYS if k in node}
        for uid, node in (manifest.get("nodes") or {}).items()
        if node.get("resource_type") in KEEP_RESOURCE_TYPES
    }
    return {
        "metadata": {k: metadata[k] for k in KEEP_METADATA if k in metadata},
        "nodes": nodes,
        "sources": manifest.get("sources") or {},
    }


def write_slim(source: Path, dest: Path, *, gzipped: bool = False) -> None:
    slim = slim_manifest(json.loads(source.read_text(encoding="utf-8")))
    data = json.dumps(slim, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    payload = data.encode("utf-8")
    if gzipped:
        # mtime=0 keeps the gzip header stable between runs.
        payload = gzip.compress(payload, compresslevel=9, mtime=0)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a slimmed copy of a dbt manifest.json.")
    parser.add_argument("source", type=Path, help="path to a dbt manifest.json")
    parser.add_argument("dest", type=Path, help="where to write the slim manifest")
    parser.add_argument("--gzip", action="store_true", help="gzip the output")
    args = parser.parse_args(argv)
    write_slim(args.source, args.dest, gzipped=args.gzip)
    print(f"wrote {args.dest} ({args.dest.stat().st_size:,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
