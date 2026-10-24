# PirateFinder Catalogue JSON

Unofficial converter for the [PirateFinder](https://github.com/peteclarke-del/PirateFinder)
catalogue. It downloads the weekly read-only SQLite catalogue, verifies its
SHA-256 and publishes the same information as portable JSON — including disks,
contents, hashes, **media addresses/credits** and **trivia**.

The converter is generic: it contains no data or references from any game
archive or launcher. It is not affiliated with PirateFinder.

- **Code:** MIT (`LICENSE`)
- **Generated data:** CC BY-NC-SA 4.0 (`LICENSE-DATA`), non-commercial
- **Attribution:** see `NOTICE`
- **No disk images** are included; only metadata, hashes, URLs and credits.

## Why

PirateFinder's catalogue is a 300+ MB SQLite database. Many consumers only
need the catalogue metadata and cannot (or do not want to) ship a SQLite
library. This project converts it once (in CI) into compact JSON that can be
downloaded and read with any JSON parser.

## Requirements

- Python 3.12 (standard library only)
- Network access for `fetch` (GitHub release download)

## Usage

```sh
./run.sh fetch                         # newest catalogue-* release, SHA-256 verified
./run.sh convert --platform all        # all platforms -> dist/*.json
./run.sh convert --platform atari-st --gzip
./run.sh convert --platform amiga --split
./run.sh update                        # fetch + build all/atari-st/amiga .json.gz + latest.json
```

A local `.venv` is used automatically when present; otherwise `python3`.

`fetch` writes to `work/` (git-ignored):

```
work/raw/catalogue-layout3.sqlite.gz
work/catalogue-layout3.sqlite
work/source.json
```

`convert` writes to `dist/` (git-ignored).

## Output

Without `--split`, one document with top-level arrays:

```json
{
  "schema": 1,
  "generated_at": "2026-10-24T12:00:00Z",
  "converter": {"name": "piratefinder-catalog-json", "version": "0.1.0"},
  "source": {
    "repo": "peteclarke-del/PirateFinder",
    "tag": "catalogue-2026-10-19",
    "commit": "…",
    "asset": "catalogue-layout3.sqlite.gz",
    "sha256": "…",
    "released_at": "…",
    "fetched_at": "…",
    "catalogue_licence": "CC BY-NC-SA 4.0",
    "unofficial": true
  },
  "catalogue": {"schema_version": 3, "meta": {"…": "…"}},
  "licence": {
    "id": "CC-BY-NC-SA-4.0",
    "name": "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International",
    "url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "attribution": "…"
  },
  "unofficial": true,
  "platforms": ["amiga", "atari-st"],
  "counts": {"sources": 0, "series": 0, "crews": 0, "disks": 0, "contents": 0,
             "images": 0, "media": 0, "trivia": 0, "links": 0},
  "sources": [],
  "series": [],
  "crews": [],
  "disks": [],
  "contents": [],
  "images": [],
  "media": [],
  "trivia": [],
  "links": []
}
```

### Tables

| Array | One row per | Key fields |
|---|---|---|
| `sources` | data source | `id`, `name`, `url`, `licence`, `retrieved`, `records` |
| `series` | series | `id`, `name`, `platform`, `kind`, `group_name`, `aliases` |
| `crews` | crew name + platform | `id`, `name`, `platform`, `notes`, `members`, `founded`, `source`, `url`, `wikipedia`, `disk_count` |
| `disks` | disk/part/version | `id`, `series_id`, `number`, `label`, `title`, `platform`, `kind`, `publisher`, `cracker`, `crew`, `crew_id`, `year`, `month`, `day`, `notes`, `credits`, `menu_text`, `category` |
| `contents` | title on a disk | `disk_id`, `position`, `title`, `kind`, `publisher`, `cracker` |
| `images` | known dump | `disk_id`, `name`, `format`, `size`, `crc32`, `md5`, `sha1`, `sha512`, `bad`, `rank`, `flags`, `virus`, `virus_damage`, `antivirus` |
| `media` | picture reference | `disk_id`, `content_id`, `kind` (`menu`, `snap`, `intro`, `demo`, `title`, `boxart`), `url`, `thumb_url`, `page_url`, `credit`, `source`, `rank` |
| `trivia` | fact/note/article reference | `disk_id`, `content_id`, `kind` (`fact`, `note`, `wikipedia`), `text`, `source`, `url`, `licence` |
| `links` | reference page | `disk_id`, `label`, `url` |

Media entries are **references**, not files. `url`, `thumb_url` and `page_url`
are complete addresses; `credit` is the credit line with `{page}` expanded.
`trivia` of kind `wikipedia` stores the article title in `text`.

With `--split`, each array is written to its own file (`sources.json`,
`disks.json`, …) plus `meta.json`.

## Platform filter

`--platform all|atari-st|amiga` (default `all`). The filter applies to disks,
contents, images, media, trivia, links, series and crews; `sources` and the
catalogue metadata stay complete.

## Release assets (CI)

`.github/workflows/catalog.yml` runs weekly and on demand:

1. runs the unit tests,
2. `./run.sh update` (all + Atari ST, gzip + SHA-256),
3. uploads `dist/*` to the fixed prerelease tag `catalog-latest`:
   - `piratefinder-catalog-all.json.gz` (+ `.sha256`)
   - `piratefinder-catalog-atari-st.json.gz` (+ `.sha256`)
   - `piratefinder-catalog-amiga.json.gz` (+ `.sha256`)
   - `latest.json` (source tag, sizes, SHA-256, counts, licence)
   - `LICENSE-DATA`, `NOTICE`

Consumers should read `latest.json`, verify the asset's SHA-256, then use the
JSON. The raw SQLite database is never published.

## Licence

- **Code:** MIT — see `LICENSE`.
- **Generated data:** CC BY-NC-SA 4.0 — see `LICENSE-DATA`. You must attribute
  the source, keep it non-commercial and share adaptations under the same
  licence.
- **Attribution and source terms:** see `NOTICE`; the generated `sources`
  array records the licence/terms of every source.

This project is unofficial and is not endorsed by PirateFinder or its authors.
