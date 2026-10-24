# Copyright (c) 2026 Stefan Koelle (https://stefankoelle.de)
# Licensed under the MIT License. See LICENSE file in project root for details.
"""Unit tests for the PirateFinder catalogue JSON converter (stdlib unittest)."""

from __future__ import annotations

import gzip
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from converter import piratefinder_catalog as pc

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
    licence TEXT NOT NULL DEFAULT '', retrieved TEXT NOT NULL DEFAULT '',
    records INTEGER NOT NULL DEFAULT 0);
CREATE TABLE series (id TEXT PRIMARY KEY, name TEXT NOT NULL, platform TEXT NOT NULL,
    kind TEXT NOT NULL, group_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '');
CREATE TABLE series_alias (alias TEXT NOT NULL, series_id TEXT NOT NULL);
CREATE TABLE crews (id INTEGER PRIMARY KEY, name TEXT NOT NULL, platform TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '', members TEXT NOT NULL DEFAULT '',
    founded TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '', wikipedia TEXT NOT NULL DEFAULT '');
CREATE TABLE disks (id INTEGER PRIMARY KEY, series_id TEXT, number INTEGER,
    part TEXT NOT NULL DEFAULT '', version TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', date TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL, kind TEXT NOT NULL, publisher TEXT NOT NULL DEFAULT '',
    cracker TEXT NOT NULL DEFAULT '', condition TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '', credits TEXT NOT NULL DEFAULT '',
    menu_text TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
    crew TEXT NOT NULL DEFAULT '', crew_id INTEGER, year INTEGER, month INTEGER,
    day INTEGER, sort_title TEXT NOT NULL DEFAULT '');
CREATE TABLE contents (id INTEGER PRIMARY KEY, disk_id INTEGER NOT NULL,
    position INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL,
    kind TEXT NOT NULL, publisher TEXT NOT NULL DEFAULT '',
    cracker TEXT NOT NULL DEFAULT '', version TEXT NOT NULL DEFAULT '',
    extra TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '');
CREATE TABLE images (id INTEGER PRIMARY KEY, disk_id INTEGER NOT NULL,
    name TEXT NOT NULL, format TEXT NOT NULL, flags TEXT NOT NULL DEFAULT '',
    size INTEGER, crc32 TEXT NOT NULL DEFAULT '', md5 TEXT NOT NULL DEFAULT '',
    sha1 TEXT NOT NULL DEFAULT '', sha512 TEXT NOT NULL DEFAULT '',
    bad INTEGER NOT NULL DEFAULT 0, rank INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '', virus TEXT NOT NULL DEFAULT '',
    virus_damage INTEGER NOT NULL DEFAULT 0, antivirus TEXT NOT NULL DEFAULT '');
CREATE TABLE address_prefix (id INTEGER PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE media_credit (id INTEGER PRIMARY KEY, source TEXT NOT NULL, credit TEXT NOT NULL);
CREATE TABLE media (id INTEGER PRIMARY KEY, disk_id INTEGER NOT NULL,
    content_id INTEGER, kind TEXT NOT NULL, url_prefix INTEGER NOT NULL,
    url TEXT NOT NULL, thumb_prefix INTEGER, thumb_url TEXT, width INTEGER,
    height INTEGER, credit_id INTEGER NOT NULL, page_prefix INTEGER,
    page_url TEXT NOT NULL DEFAULT '', rank INTEGER NOT NULL DEFAULT 100);
CREATE TABLE trivia (id INTEGER PRIMARY KEY, disk_id INTEGER, content_id INTEGER,
    kind TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '', licence TEXT NOT NULL DEFAULT '');
CREATE TABLE links (disk_id INTEGER NOT NULL, label TEXT NOT NULL, url TEXT NOT NULL);
"""


class ExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.executescript(
            """
            INSERT INTO meta VALUES ('schema_version', '3');
            INSERT INTO meta VALUES ('licence', 'CC BY-NC-SA 4.0');
            INSERT INTO sources VALUES ('atari-legend', 'Atari Legend', 'https://atarilegend.com',
                'CC BY-NC-SA 4.0', '2026-10-19', 10);
            INSERT INTO series VALUES ('automation', 'Automation', 'atari-st', 'menu', 'Automation', '');
            INSERT INTO series VALUES ('skid-row', 'Skid Row', 'amiga', 'menu', 'Skid Row', '');
            INSERT INTO series_alias VALUES ('auto', 'automation');
            INSERT INTO crews VALUES (1, 'Automation', 'atari-st', 'A crew', 'A, B', '1985',
                'atari-legend', 'https://atarilegend.com/menusets/1', '');
            INSERT INTO crews VALUES (2, 'Skid Row', 'amiga', 'An Amiga crew', 'C', '1987',
                'demozoo', 'https://demozoo.org/groups/1/', '');
            INSERT INTO disks VALUES (10, 'automation', 250, '', '', 'Automation 250',
                'Automation 250 (1990)(Automation)', '', 'atari-st', 'menu', 'Automation',
                '', '', 'Notes', 'Credits', 'Scroll text', 'Games', 'Automation', 1, 1990, 6, 1,
                'automation 250');
            INSERT INTO disks VALUES (20, 'skid-row', 1, '', '', 'Skid Row 1',
                'Skid Row 1 (1988)(Skid Row)', '', 'amiga', 'menu', 'Skid Row',
                '', '', '', '', '', 'Games', 'Skid Row', 2, 1988, NULL, NULL, 'skid row 1');
            INSERT INTO contents VALUES (100, 10, 1, 'Necron', 'game', 'Automation', '', '', '', 'atari-legend');
            INSERT INTO contents VALUES (200, 20, 1, 'Amiga Game', 'game', 'Skid Row', '', '', '', 'tosec');
            INSERT INTO images VALUES (1000, 10, 'Automation 250.st', 'st', '[!]', 737280,
                '12345678', 'md5', 'sha1', 'sha512', 0, 1, 'tosec', '', 0, '');
            INSERT INTO images VALUES (2000, 20, 'Skid Row 1.adf', 'adf', '', 901120,
                '', '', '', '', 1, 1, 'tosec', '', 0, '');
            INSERT INTO address_prefix VALUES (0, '');
            INSERT INTO address_prefix VALUES (1, 'https://example.org/img/');
            INSERT INTO address_prefix VALUES (2, 'https://example.org/page/');
            INSERT INTO media_credit VALUES (1, 'demozoo', 'Demozoo contributors, {page}');
            INSERT INTO media VALUES (500, 10, NULL, 'menu', 1, 'menu.png', NULL, NULL,
                NULL, NULL, 1, 2, 'production/100/', 1);
            INSERT INTO media VALUES (501, 10, NULL, 'snap', 1, 'snap.png', 1, 'thumb.png',
                NULL, NULL, 1, NULL, '', 2);
            INSERT INTO media VALUES (502, 20, NULL, 'menu', 1, 'amiga.png', NULL, NULL,
                NULL, NULL, 1, NULL, '', 1);
            INSERT INTO trivia VALUES (900, 10, NULL, 'fact', 'A fact', 'atari-legend',
                'https://atarilegend.com/x', 'CC BY-NC-SA 4.0');
            INSERT INTO trivia VALUES (901, 20, NULL, 'wikipedia', 'Amiga Game', 'wikipedia',
                '', 'CC BY-SA 4.0');
            INSERT INTO links VALUES (10, 'Atari Legend', 'https://atarilegend.com/menusets/1');
            INSERT INTO links VALUES (20, 'Demozoo', 'https://demozoo.org/productions/1/');
            """
        )
        self.source = {"repo": pc.REPO, "tag": "catalogue-2026-10-19", "sha256": "abc"}

    def tearDown(self) -> None:
        self.db.close()

    def test_filters_atari_st(self) -> None:
        payload = pc.extract_catalogue(self.db, "atari-st", self.source)
        self.assertEqual([d["id"] for d in payload["disks"]], [10])
        self.assertEqual([c["id"] for c in payload["crews"]], [1])
        self.assertEqual([s["id"] for s in payload["series"]], ["automation"])
        self.assertEqual([c["title"] for c in payload["contents"]], ["Necron"])
        self.assertEqual([i["id"] for i in payload["images"]], [1000])
        self.assertEqual([m["id"] for m in payload["media"]], [500, 501])
        self.assertEqual([t["id"] for t in payload["trivia"]], [900])
        self.assertEqual(len(payload["links"]), 1)
        self.assertEqual(payload["counts"]["disks"], 1)
        self.assertEqual(payload["counts"]["media"], 2)

    def test_media_addresses_and_credit(self) -> None:
        payload = pc.extract_catalogue(self.db, "atari-st", self.source)
        media = {item["id"]: item for item in payload["media"]}
        self.assertEqual(media[500]["url"], "https://example.org/img/menu.png")
        self.assertEqual(media[500]["thumb_url"], "https://example.org/img/menu.png")
        self.assertEqual(
            media[500]["page_url"], "https://example.org/page/production/100/"
        )
        self.assertEqual(
            media[500]["credit"],
            "Demozoo contributors, example.org/page/production/100/",
        )
        self.assertEqual(media[500]["source"], "demozoo")
        self.assertEqual(media[501]["thumb_url"], "https://example.org/img/thumb.png")

    def test_series_aliases_and_crew_disk_count(self) -> None:
        payload = pc.extract_catalogue(self.db, "all", self.source)
        series = {item["id"]: item for item in payload["series"]}
        self.assertEqual(series["automation"]["aliases"], ["auto"])
        crews = {item["id"]: item for item in payload["crews"]}
        self.assertEqual(crews[1]["disk_count"], 1)
        self.assertEqual(crews[2]["disk_count"], 1)
        self.assertEqual(payload["platforms"], ["amiga", "atari-st"])

    def test_bad_image_is_boolean(self) -> None:
        payload = pc.extract_catalogue(self.db, "amiga", self.source)
        self.assertTrue(payload["images"][0]["bad"])

    def test_unsupported_schema_raises(self) -> None:
        self.db.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
        with self.assertRaises(SystemExit):
            pc.extract_catalogue(self.db, "all", self.source)


class HelperTests(unittest.TestCase):
    def test_normalize_platform(self) -> None:
        self.assertEqual(pc.normalize_platform("st"), "atari-st")
        self.assertEqual(pc.normalize_platform("Atari ST"), "atari-st")
        self.assertEqual(pc.normalize_platform("amiga"), "amiga")
        self.assertEqual(pc.normalize_platform("all"), "all")

    def test_platform_list(self) -> None:
        self.assertEqual(pc.platform_list("all,atari-st"), ["all", "atari-st"])
        self.assertEqual(pc.platform_list("atari-st,amiga"), ["atari-st", "amiga"])
        self.assertEqual(
            pc.platform_list("all,atari-st,amiga"), ["all", "atari-st", "amiga"]
        )

    def test_credit_with_literal_braces(self) -> None:
        self.assertEqual(
            pc.format_media_credit("A {{literal}} at {page}", "https://example.org/x/"),
            "A {literal} at example.org/x/",
        )

    def test_gzip_bundle_and_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json.gz"
            pc.write_bundle(path, {"hello": "world"})
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"hello": "world"})
            digest = pc.write_sha256(path)
            self.assertEqual(len(digest), 64)
            self.assertTrue(path.with_name(path.name + ".sha256").is_file())


if __name__ == "__main__":
    unittest.main()
