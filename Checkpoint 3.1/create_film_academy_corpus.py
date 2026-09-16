#!/usr/bin/env python3
"""Create the focused Wikipedia corpus used for film-retrieval evaluation."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = SCRIPT_DIR.parent / "Checkpoint 1.1" / "Wikipedia"
DEFAULT_OUTPUT = SCRIPT_DIR / "Wikipedia_Film_Academy"

# Fourteen award/ceremony anchors plus linked films, performers, directors, and
# craftspeople. The list is explicit so that benchmark membership is reproducible.
FILM_ACADEMY_FILES = [
    "68th_Academy_Awards.html",
    "70th_Academy_Awards.html",
    "74th_Academy_Awards.html",
    "78th_Academy_Awards.html",
    "85th_Academy_Awards.html",
    "89th_Academy_Awards.html",
    "95th_Academy_Awards.html",
    "Academy_Award_for_Best_Actor.html",
    "Academy_Award_for_Best_Animated_Feature.html",
    "Academy_Award_for_Best_Director.html",
    "Academy_Award_for_Best_Picture.html",
    "Academy_Award_for_Best_Production_Design.html",
    "Academy_Award_for_Best_Supporting_Actor.html",
    "List_of_Academy_Award_records.html",
    "Steven_Spielberg.html",
    "Titanic_(1997_film).html",
    "Jack_Nicholson.html",
    "La_La_Land.html",
    "Brokeback_Mountain.html",
    "William_Wyler.html",
    "The_Godfather_Part_II.html",
    "Damien_Chazelle.html",
    "Ben_Kingsley.html",
    "Sam_Mendes.html",
    "Jill_Quertier.html",
    "Martin_Childs.html",
    "Andrew_Lesnie.html",
    "BAFTA_Award_for_Best_Actor_in_a_Supporting_Role.html",
    "Emmanuel_Lubezki.html",
    "Frank_Perry.html",
    "Deconstructing_Harry.html",
    "A_Single_Man.html",
    "The_Wings_of_the_Dove_(1997_film).html",
    "Anthony_Minghella.html",
    "Tim_Robbins.html",
    "Andrea_Riseborough.html",
    "The_Absent-Minded_Professor.html",
    "Starman_(film).html",
    "Kramer_vs._Kramer.html",
    "Lonesome_Dove.html",
    "Sally_Field.html",
    "Gus_Van_Sant.html",
    "Peter_Fonda.html",
    "Jonathan_Demme.html",
    "Stanley_Tucci.html",
    "Paul_Mescal.html",
    "A_Beautiful_Day_in_the_Neighborhood.html",
    "Japan_Academy_Film_Prize.html",
    "Brendan_Fraser.html",
    "Danny_DeVito.html",
    "Bill_Nighy.html",
    "Robert_Zemeckis.html",
    "Michael_B._Jordan.html",
    "King_Kong_(1976_film).html",
    "Trolls_(film).html",
    "Whiplash_(2014_film).html",
    "Steve_Carell.html",
    "Austin_Butler.html",
    "Kevin_Costner.html",
    "The_Song_(2014_film).html",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()

    missing = [filename for filename in FILM_ACADEMY_FILES if not (source / filename).is_file()]
    if missing:
        raise SystemExit("Missing source files:\n" + "\n".join(missing))

    output.mkdir(parents=True, exist_ok=True)
    expected = set(FILM_ACADEMY_FILES)
    unexpected = [path for path in output.glob("*.html") if path.name not in expected]
    if unexpected:
        raise SystemExit(
            "Output contains HTML files outside the manifest; remove or move them first:\n"
            + "\n".join(str(path) for path in unexpected)
        )

    for filename in FILM_ACADEMY_FILES:
        shutil.copy2(source / filename, output / filename)

    manifest = {
        "purpose": "Focused film and Academy Awards retrieval-evaluation corpus",
        "source_directory": str(source),
        "article_count": len(FILM_ACADEMY_FILES),
        "files": FILM_ACADEMY_FILES,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    raw_bytes = sum((output / filename).stat().st_size for filename in FILM_ACADEMY_FILES)
    print(f"Copied {len(FILM_ACADEMY_FILES)} articles to: {output}")
    print(f"Raw HTML size: {raw_bytes / 1024 / 1024:.2f} MiB")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()