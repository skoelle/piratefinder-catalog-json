#!/usr/bin/env python3
# Copyright (c) 2026 Stefan Koelle (https://stefankoelle.de)
# Licensed under the MIT License. See LICENSE file in project root for details.
"""Convert the PirateFinder catalogue into a portable JSON dataset.

PirateFinder publishes a read-only SQLite catalogue (CC BY-NC-SA 4.0) as a
weekly GitHub release.  This converter fetches that release, verifies its
SHA-256, extracts the catalogue tables (including media URLs and trivia) and
writes compact JSON that other programs can consume without SQLite.

It is an unofficial, independent project.  It contains no data or references
from any game archive: the output is derived only from PirateFinder's
catalogue.  The generated data is licensed CC BY-NC-SA 4.0; see
``LICENSE-DATA`` and ``NOTICE``.

Commands::

    python -m converter fetch [--tag catalogue-YYYY-MM-DD] [--force]
    python -m converter convert [--platform all|atari-st|amiga] [--gzip]
    python -m converter update [--platforms all,atari-st,amiga]

See README.md for the output schema and the licence terms.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

TOOL_VERSION = "0.1.0"
OUTPUT_SCHEMA = 1
EXPECTED_CATALOGUE_SCHEMA = 3

REPO = "peteclarke-del/PirateFinder"
API_ROOT = "https://api.github.com/repos/" + REPO
TAG_PREFIX = "catalogue-"
USER_AGENT = f"piratefinder-catalog-json/{TOOL_VERSION} (+https://github.com/skoelle/piratefinder-catalog-json)"

LICENCE = {
    "id": "CC-BY-NC-SA-4.0",
    "name": "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
    "url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "attribution": (
        "PirateFinder catalogue by Pete Clarke and contributors; includes Atari Legend "
        "data and other sources listed in the catalogue's sources table. See NOTICE."
    ),
}


# --------------------------------------------------------------------------
# Paths and helpers
# --------------------------------------------------------------------------


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_work() -> Path:
    return repo_root() / "work"


def default_out() -> Path:
    return repo_root() / "dist"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    print(message, flush=True)


def fmt_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB")
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{value} B"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: object, *, pretty: bool = False) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        if pretty:
            json.dump(payload, handle, ensure_ascii=False, indent=1, sort_keys=False)
        else:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=False,
            )
        handle.write("\n")
    os.replace(tmp, path)


def write_bundle(path: Path, payload: object, *, pretty: bool = False) -> None:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        indent=1 if pretty else None,
        separators=None if pretty else (",", ":"),
        sort_keys=False,
    )
    ensure_dir(path.parent)
    if path.suffix == ".gz":
        with gzip.GzipFile(filename=str(path), mode="wb", mtime=0) as handle:
            handle.write((data + "\n").encode("utf-8"))
    else:
        path.write_text(data + "\n", encoding="utf-8")


def write_sha256(path: Path) -> str:
    digest = sha256_file(path)
    path.with_name(path.name + ".sha256").write_text(
        f"{digest}  {path.name}\n", encoding="utf-8"
    )
    return digest


def normalize_platform(value: str) -> str:
    text = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    if text in {"", "all", "*", "both", "any"}:
        return "all"
    if text in {"st", "atari-st", "atari"}:
        return "atari-st"
    if text in {"amiga", "commodore-amiga"}:
        return "amiga"
    raise SystemExit(f"error: unknown platform {value!r} (use all, atari-st or amiga)")


def platform_list(value: str) -> list[str]:
    result = []
    for item in value.split(","):
        platform = normalize_platform(item)
        if platform not in result:
            result.append(platform)
    return result or ["all"]


# --------------------------------------------------------------------------
# GitHub / fetch
# --------------------------------------------------------------------------


def http_json(url: str) -> object:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:400]
        raise SystemExit(
            f"error: GitHub request failed ({error.code}): {url}\n{body}"
        ) from error
    except urllib.error.URLError as error:
        raise SystemExit(f"error: cannot reach GitHub: {error.reason}") from error


def download_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise SystemExit(str(error.reason)) from error


def download(
    url: str, destination: Path, *, expect_sha256: str = "", force: bool = False
) -> str:
    if destination.is_file() and not force:
        digest = sha256_file(destination)
        if not expect_sha256 or digest == expect_sha256:
            log(
                f"  cached {destination.name} ({fmt_bytes(destination.stat().st_size)})"
            )
            return digest
        log(f"  cached {destination.name} has the wrong SHA-256, downloading again")
    ensure_dir(destination.parent)
    part = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            part.open("wb") as handle,
        ):
            total = int(response.headers.get("Content-Length") or 0)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
                if total and (
                    size // (10 * 1024 * 1024)
                    != (size - len(chunk)) // (10 * 1024 * 1024)
                ):
                    log(
                        f"  {destination.name}: {size / total * 100:5.1f}% ({fmt_bytes(size)})"
                    )
    except urllib.error.HTTPError as error:
        raise SystemExit(f"error: download failed ({error.code}): {url}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"error: download failed: {error.reason}") from error
    os.replace(part, destination)
    actual = digest.hexdigest()
    if expect_sha256 and actual != expect_sha256:
        destination.unlink(missing_ok=True)
        raise SystemExit(
            f"error: SHA-256 mismatch for {destination.name}: got {actual}, expected {expect_sha256}"
        )
    log(
        f"  saved {destination.name} ({fmt_bytes(size)}, {time.monotonic() - started:.1f}s)"
    )
    return actual


def find_release(tag: str) -> dict:
    if tag:
        return http_json(f"{API_ROOT}/releases/tags/{tag}")  # type: ignore[return-value]
    releases = http_json(f"{API_ROOT}/releases?per_page=100")
    if not isinstance(releases, list):
        raise SystemExit("error: unexpected GitHub release response")
    candidates = [
        item
        for item in releases
        if str(item.get("tag_name", "")).startswith(TAG_PREFIX)
    ]
    if not candidates:
        raise SystemExit(
            f"error: no {TAG_PREFIX}* release found in the last 100 releases"
        )
    candidates.sort(
        key=lambda item: item.get("published_at") or item.get("created_at") or "",
        reverse=True,
    )
    return candidates[0]


def fetch_release(tag: str, work: Path, *, force: bool = False) -> dict:
    log("fetch: resolving PirateFinder catalogue release")
    release = find_release(tag)
    tag_name = str(release.get("tag_name", ""))
    commit = str(release.get("target_commitish", "") or "")
    assets = release.get("assets") or []
    candidates = [
        item
        for item in assets
        if re.fullmatch(r"catalogue-layout\d+\.sqlite\.gz", str(item.get("name", "")))
    ]
    if not candidates:
        raise SystemExit(
            f"error: release {tag_name} has no catalogue-layout*.sqlite.gz asset"
        )
    expected_name = f"catalogue-layout{EXPECTED_CATALOGUE_SCHEMA}.sqlite.gz"
    asset = next(
        (item for item in candidates if str(item.get("name", "")) == expected_name),
        candidates[0],
    )
    asset_name = str(asset["name"])
    sha_asset = next(
        (item for item in assets if str(item.get("name", "")).endswith(".sha256")), None
    )
    expected_sha = ""
    if sha_asset:
        text = download_text(str(sha_asset["browser_download_url"]))
        first = text.strip().split()[0] if text.strip() else ""
        if re.fullmatch(r"[0-9a-fA-F]{64}", first):
            expected_sha = first.lower()
    elif asset.get("digest"):
        digest = str(asset["digest"])
        if digest.startswith("sha256:"):
            expected_sha = digest.split(":", 1)[1].lower()

    log(f"  release {tag_name} (commit {commit[:12] or 'unknown'}), asset {asset_name}")
    raw = ensure_dir(work / "raw")
    archive = raw / asset_name
    actual_sha = download(
        str(asset["browser_download_url"]),
        archive,
        expect_sha256=expected_sha,
        force=force,
    )

    sqlite_name = (
        asset_name[:-3] if asset_name.endswith(".gz") else asset_name + ".sqlite"
    )
    sqlite_path = work / sqlite_name
    if force or not sqlite_path.is_file() or sqlite_path.stat().st_size == 0:
        log(f"  unpacking {asset_name} -> {sqlite_name}")
        tmp = sqlite_path.with_suffix(sqlite_path.suffix + ".tmp")
        with gzip.open(archive, "rb") as source, tmp.open("wb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
        os.replace(tmp, sqlite_path)
    with sqlite_path.open("rb") as handle:
        header = handle.read(16)
    if not header.startswith(b"SQLite format 3\x00"):
        raise SystemExit(f"error: {sqlite_path} is not a SQLite database")
    log(f"  database {sqlite_path.name} ({fmt_bytes(sqlite_path.stat().st_size)})")

    source = {
        "repo": REPO,
        "tag": tag_name,
        "commit": commit,
        "release_id": release.get("id"),
        "asset": asset_name,
        "sha256": actual_sha,
        "sqlite": sqlite_name,
        "released_at": release.get("published_at"),
        "fetched_at": utc_now(),
        "catalogue_licence": "CC BY-NC-SA 4.0",
        "unofficial": True,
    }
    write_json(work / "source.json", source, pretty=True)
    log(f"fetch: done; source metadata in {work / 'source.json'}")
    return source


def read_source(work: Path) -> dict:
    path = work / "source.json"
    if not path.is_file():
        raise SystemExit(f"error: {path} not found; run `fetch` first")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_sqlite(work: Path) -> Path:
    source = read_source(work)
    candidate = work / str(source.get("sqlite", ""))
    if candidate.is_file():
        return candidate
    matches = sorted(work.glob("catalogue-layout*.sqlite"))
    if matches:
        return matches[-1]
    raise SystemExit("error: no catalogue database found; run `fetch` first")


def connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def format_media_credit(template: str, page_url: str) -> str:
    """Fill PirateFinder's credit template (``{page}`` is the page without scheme)."""
    page = re.sub(r"^https?://", "", page_url or "")
    try:
        return template.format(page=page)
    except (KeyError, ValueError, IndexError):
        return template.replace("{page}", page)


def rows(connection: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    return list(connection.execute(sql))


def extract_catalogue(
    connection: sqlite3.Connection, platform: str, source: dict
) -> dict:
    """Build the JSON payload for one platform (``all`` for both)."""
    meta = {
        str(row["key"]): str(row["value"])
        for row in rows(connection, "SELECT key, value FROM meta")
    }
    schema = int(meta.get("schema_version", "0"))
    if schema != EXPECTED_CATALOGUE_SCHEMA:
        raise SystemExit(
            f"error: catalogue schema {schema} is not supported "
            f"(expected {EXPECTED_CATALOGUE_SCHEMA}); update the converter"
        )

    all_disks = [
        dict(row)
        for row in rows(
            connection,
            """
            SELECT id, series_id, number, part, version, label, title, date, platform,
                   kind, publisher, cracker, condition, notes, credits, menu_text,
                   category, crew, crew_id, year, month, day, sort_title
            FROM disks ORDER BY id
            """,
        )
    ]
    disks = [
        item
        for item in all_disks
        if platform == "all" or str(item["platform"]) == platform
    ]
    disk_ids = {int(item["id"]) for item in disks}

    alias_map: dict[str, list[str]] = defaultdict(list)
    for row in rows(
        connection, "SELECT alias, series_id FROM series_alias ORDER BY alias"
    ):
        alias_map[str(row["series_id"])].append(str(row["alias"]))
    series = []
    for row in rows(
        connection,
        "SELECT id, name, platform, kind, group_name, description FROM series ORDER BY id",
    ):
        item = dict(row)
        if platform != "all" and str(item["platform"]) != platform:
            continue
        item["aliases"] = alias_map.get(str(item["id"]), [])
        series.append(item)

    disk_count = Counter(
        item["crew_id"] for item in disks if item.get("crew_id") is not None
    )
    crews = []
    for row in rows(
        connection,
        """
        SELECT id, name, platform, notes, members, founded, source, url, wikipedia
        FROM crews ORDER BY name, id
        """,
    ):
        item = dict(row)
        if platform != "all" and str(item["platform"]) != platform:
            continue
        item["disk_count"] = disk_count.get(item["id"], 0)
        crews.append(item)

    def table(name: str, order: str) -> list[dict]:
        result = []
        for row in rows(connection, f"SELECT * FROM {name} ORDER BY {order}"):
            item = dict(row)
            disk_id = item.get("disk_id")
            if disk_id is not None and int(disk_id) in disk_ids:
                result.append(item)
        return result

    contents = table("contents", "disk_id, position, id")
    images = table("images", "disk_id, rank, id")
    for image in images:
        image["bad"] = bool(image.get("bad"))
        image["virus_damage"] = bool(image.get("virus_damage"))
    trivia = table("trivia", "disk_id, id")
    links = table("links", "disk_id, label")

    media = []
    media_sql = """
        SELECT m.id, m.disk_id, m.content_id, m.kind, m.width, m.height, m.rank,
               (COALESCE(up.text, '') || m.url) AS url,
               CASE WHEN m.thumb_url IS NULL
                    THEN (COALESCE(up.text, '') || m.url)
                    ELSE (COALESCE(tp.text, '') || m.thumb_url)
               END AS thumb_url,
               CASE WHEN m.page_prefix IS NULL THEN ''
                    ELSE (COALESCE(pp.text, '') || m.page_url)
               END AS page_url,
               mc.source AS credit_source, mc.credit AS credit_template
        FROM media m
        JOIN address_prefix up ON up.id = m.url_prefix
        LEFT JOIN address_prefix tp ON tp.id = m.thumb_prefix
        LEFT JOIN address_prefix pp ON pp.id = m.page_prefix
        JOIN media_credit mc ON mc.id = m.credit_id
        ORDER BY m.disk_id, m.rank, m.id
    """
    for row in rows(connection, media_sql):
        item = dict(row)
        if item.get("disk_id") is None or int(item["disk_id"]) not in disk_ids:
            continue
        template = str(item.pop("credit_template") or "")
        page_url = str(item.get("page_url") or "")
        item["credit"] = format_media_credit(template, page_url)
        item["source"] = item.pop("credit_source")
        media.append(item)

    sources = [
        dict(row) for row in rows(connection, "SELECT * FROM sources ORDER BY id")
    ]

    platforms = sorted({str(item["platform"]) for item in disks})
    payload = {
        "schema": OUTPUT_SCHEMA,
        "generated_at": utc_now(),
        "converter": {"name": "piratefinder-catalog-json", "version": TOOL_VERSION},
        "source": source,
        "catalogue": {"schema_version": schema, "meta": meta},
        "licence": LICENCE,
        "unofficial": True,
        "platforms": platforms,
        "counts": {
            "sources": len(sources),
            "series": len(series),
            "crews": len(crews),
            "disks": len(disks),
            "contents": len(contents),
            "images": len(images),
            "media": len(media),
            "trivia": len(trivia),
            "links": len(links),
        },
        "sources": sources,
        "series": series,
        "crews": crews,
        "disks": disks,
        "contents": contents,
        "images": images,
        "media": media,
        "trivia": trivia,
        "links": links,
    }
    return payload


def convert_one(
    work: Path,
    out: Path,
    platform: str,
    *,
    gzip_output: bool,
    pretty: bool,
    split: bool,
    name: str,
) -> tuple[dict, list[Path]]:
    sqlite_path = find_sqlite(work)
    source = read_source(work)
    connection = connect_readonly(sqlite_path)
    try:
        payload = extract_catalogue(connection, platform, source)
    finally:
        connection.close()

    if split:
        directory = ensure_dir(out / name)
        meta_payload = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "sources",
                "series",
                "crews",
                "disks",
                "contents",
                "images",
                "media",
                "trivia",
                "links",
            }
        }
        write_json(directory / "meta.json", meta_payload, pretty=pretty)
        written = [directory / "meta.json"]
        for key in (
            "sources",
            "series",
            "crews",
            "disks",
            "contents",
            "images",
            "media",
            "trivia",
            "links",
        ):
            path = directory / f"{key}.json"
            write_json(
                path,
                {
                    "schema": OUTPUT_SCHEMA,
                    "generated_at": payload["generated_at"],
                    "items": payload[key],
                },
                pretty=pretty,
            )
            written.append(path)
        return payload, written

    suffix = ".json.gz" if gzip_output else ".json"
    path = out / f"{name}{suffix}"
    write_bundle(path, payload, pretty=pretty)
    written = [path]
    if gzip_output:
        write_sha256(path)
        written.append(path.with_name(path.name + ".sha256"))
    log(
        f"convert: {platform}: {payload['counts']['disks']:,} disks, "
        f"{payload['counts']['media']:,} media, {payload['counts']['trivia']:,} trivia -> {path}"
    )
    return payload, written


def write_latest(out: Path, source: dict, assets: dict[str, dict]) -> Path:
    payload = {
        "schema": OUTPUT_SCHEMA,
        "generated_at": utc_now(),
        "converter": {"name": "piratefinder-catalog-json", "version": TOOL_VERSION},
        "source": source,
        "licence": LICENCE,
        "unofficial": True,
        "assets": assets,
    }
    path = out / "latest.json"
    write_json(path, payload, pretty=True)
    return path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def cmd_fetch(args: argparse.Namespace) -> int:
    fetch_release(args.tag or "", Path(args.work).expanduser(), force=args.force)
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    work = Path(args.work).expanduser()
    out = ensure_dir(Path(args.out).expanduser())
    platform = normalize_platform(args.platform)
    name = args.name or f"piratefinder-catalog-{platform}"
    convert_one(
        work,
        out,
        platform,
        gzip_output=args.gzip,
        pretty=args.pretty,
        split=args.split,
        name=name,
    )
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    work = Path(args.work).expanduser()
    out = ensure_dir(Path(args.out).expanduser())
    source = fetch_release(args.tag or "", work, force=args.force)
    assets: dict[str, dict] = {}
    for platform in platform_list(args.platforms):
        name = f"piratefinder-catalog-{platform}"
        payload, written = convert_one(
            work,
            out,
            platform,
            gzip_output=True,
            pretty=args.pretty,
            split=False,
            name=name,
        )
        bundle = next(path for path in written if path.suffix == ".gz")
        digest = sha256_file(bundle)
        assets[platform] = {
            "file": bundle.name,
            "size": bundle.stat().st_size,
            "sha256": digest,
            "counts": payload["counts"],
        }
    for filename in ("LICENSE-DATA", "NOTICE"):
        source_file = repo_root() / filename
        if source_file.is_file():
            (out / filename).write_text(
                source_file.read_text(encoding="utf-8"), encoding="utf-8"
            )
    latest = write_latest(out, source, assets)
    log(f"update: {len(assets)} asset(s), pointer in {latest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert the PirateFinder catalogue into portable JSON."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser(
        "fetch", help="download the newest catalogue release and verify its checksum"
    )
    fetch.add_argument(
        "--tag", help="specific catalogue tag, e.g. catalogue-2026-10-19"
    )
    fetch.add_argument("--work", default=str(default_work()), help="working directory")
    fetch.add_argument(
        "--force", action="store_true", help="download/extract again even when cached"
    )
    fetch.set_defaults(func=cmd_fetch)

    convert = sub.add_parser("convert", help="extract the catalogue into JSON")
    convert.add_argument(
        "--platform", default="all", help="all, atari-st or amiga (default: all)"
    )
    convert.add_argument(
        "--work", default=str(default_work()), help="working directory"
    )
    convert.add_argument("--out", default=str(default_out()), help="output directory")
    convert.add_argument(
        "--gzip", action="store_true", help="write .json.gz plus .sha256"
    )
    convert.add_argument("--pretty", action="store_true", help="indent the JSON")
    convert.add_argument(
        "--split", action="store_true", help="write one JSON file per table"
    )
    convert.add_argument(
        "--name", help="output base name (default: piratefinder-catalog-<platform>)"
    )
    convert.set_defaults(func=cmd_convert)

    update = sub.add_parser(
        "update", help="fetch and build the release assets + latest.json"
    )
    update.add_argument("--tag", help="specific catalogue tag")
    update.add_argument(
        "--platforms", default="all,atari-st,amiga", help="comma-separated platforms"
    )
    update.add_argument("--work", default=str(default_work()), help="working directory")
    update.add_argument("--out", default=str(default_out()), help="output directory")
    update.add_argument(
        "--force", action="store_true", help="download/extract again even when cached"
    )
    update.add_argument("--pretty", action="store_true", help="indent the JSON")
    update.set_defaults(func=cmd_update)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
