from bs4 import BeautifulSoup
from pathlib import Path
import collections, json

signals = collections.Counter()
per_file = {}
root = Path(r"C:\Users\steph\OneDrive\Documents\MIT RAG\Capstone\Checkpoint 1.1\Wikipedia")

for p in root.glob("*.html"):
    html = p.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    s = {
        # Strong SMW / RDFa signals
        "rdfa_typeof":  len(soup.select("[typeof]")),
        "rdfa_property": len(soup.select("[property]")),
        "microdata_itemtype": len(soup.select("[itemtype]")),
        "smw_factbox": len(soup.select(".smwfact, .smwrdflink, .smwttinline")),
        "parsoid_version": bool(soup.find("meta", attrs={"property":"mw:html:version"})),
        # Wikipedia structural signals
        "infobox": len(soup.select("table.infobox")),
        "wikitable": len(soup.select("table.wikitable")),
        "categories": len(soup.select("#mw-normal-catlinks li, .catlinks a")),
        "wikilinks": len(soup.select('a[href^="/wiki/"], a[rel~="mw:WikiLink"]')),
        "hatnotes": len(soup.select(".hatnote")),
    }
    per_file[p.name] = s
    for k,v in s.items():
        if v: signals[k]+=1

print(json.dumps(signals, indent=2))