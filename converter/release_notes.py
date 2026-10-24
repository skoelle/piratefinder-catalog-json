#!/usr/bin/env python3
# Copyright (c) 2026 Stefan Koelle (https://stefankoelle.de)
# Licensed under the MIT License. See LICENSE file in project root for details.
"""Render the GitHub release notes from a generated latest.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLATFORM_ORDER = ("all", "atari-st", "amiga")


def render(payload: dict) -> str:
    source = payload.get("source") or {}
    converter = payload.get("converter") or {}
    assets = payload.get("assets") or {}
    lines = [
        "Automatically generated from the PirateFinder catalogue.",
        "",
        f"- Catalogue: `{source.get('tag', '?')}`",
        f"- Generated: `{payload.get('generated_at', '?')}`",
        (
            f"- Converter: `{converter.get('name', 'piratefinder-catalog-json')} "
            f"{converter.get('version', '?')}`"
        ),
        "- Licence: CC BY-NC-SA 4.0 (see `LICENSE-DATA` and `NOTICE`)",
        "",
        "| Asset | Size | Disks | Media | Trivia |",
        "|---|---:|---:|---:|---:|",
    ]
    for key in PLATFORM_ORDER:
        asset = assets.get(key)
        if not asset:
            continue
        counts = asset.get("counts") or {}
        lines.append(
            f"| `{asset.get('file', '?')}` | {asset.get('size', 0):,} | "
            f"{counts.get('disks', 0):,} | {counts.get('media', 0):,} | "
            f"{counts.get('trivia', 0):,} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m converter.release_notes <latest.json>", file=sys.stderr)
        return 2
    payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    sys.stdout.write(render(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
