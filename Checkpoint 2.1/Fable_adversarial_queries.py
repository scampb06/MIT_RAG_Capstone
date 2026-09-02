"""Round-2 adversarial queries for WikipediaHybridRetriever (Checkpoint 2.1).

Every fact below was verified against article text captured in
checkpoint_2_1_retrieval.log, so each query IS answerable from the corpus
(or from the raw HTML) — the retriever/extractor is what should fail.
"""


def adversarial_queries_round2() -> list[str]:
    return [
        # 1. Deep detail, ~36k chars into a 160k-char article, phrased with no
        #    title vocabulary ("Tōhoku", "Japan", "earthquake", "tsunami").
        #    Whole-article embedding is a diluted average of ~5 chunks, and BM25's
        #    length normalization punishes this very long document, so short
        #    Norway/fjord-heavy articles should outrank it.
        "On the day of a 2011 Pacific megathrust quake, the water in several "
        "Scandinavian fjords appeared to seethe as if boiling and was caught on "
        "film. Which fjord was the most prominent example, and what did "
        "scientists conclude after two years of research had caused it?",

        # 2. Infobox link-only cells are emptied by trafilatura ('Opened by',
        #    'Closed by', 'Cauldron' rows are blank), and the article's
        #    'Opening ceremony' section body is empty in the extracted text.
        #    Retrieval may find the right article, but the answer isn't in it.
        "Who officially opened the 1992 Winter Olympics in Albertville, and "
        "which two people lit the Olympic cauldron at the opening ceremony?",

        # 3. Section-header dependent: the fact lives under
        #    'Honors, recognition and legacy' > 'Estonia', ~59k chars into a
        #    112k-char biography. The query avoids the subject's name so neither
        #    BM25 nor the averaged article embedding has an anchor.
        "Which Baltic prime minister, aged 32 when he took office, said a "
        "particular free-market economist's book was the only economics book "
        "he had read before taking office? Name the book, the country, the "
        "signature reform he introduced, and the prize he won in 2006.",

        # 4. Wikitable with a two-row header and a 'Run-off' column that only
        #    exists because of a round-4 tie. The last run failed a similar
        #    bidding question (generic Olympics list pages crowded out the
        #    year-specific article), and even if retrieved, the LLM must parse
        #    a flattened pipe table whose header row is split in two.
        "In the IOC vote that awarded the 1992 Winter Games, which two cities "
        "tied and were sent to a run-off, what were their run-off vote totals, "
        "and which city was eliminated after the very first round?",

        # 5. Wikilink structure: extract_wikipedia_text() drops all hyperlinks
        #    (include_links is False) and the retriever returns at most 3 whole
        #    articles, so inbound-link enumeration and link-target questions
        #    cannot be answered from the indexed text.
        "On Yuri Shefler's article, which page does the 'Known for' infobox "
        "entry link to, and which other article in the corpus contains a "
        "wikilink pointing to Yuri Shefler's article?",
    ]


REQUIRED_FACTS: dict[int, list[str]] = {
    1: [
        "Sognefjorden (Norway)",
        "Seismic energy from the earthquake generated seiche waves thousands of "
        "kilometres away (source: 2011_Tōhoku_earthquake_and_tsunami.html, "
        "'Norway' subsection)",
    ],
    2: [
        "Opened by François Mitterrand (President of France)",
        "Cauldron lit by Michel Platini and François-Cyrille Grange "
        "(1992_Winter_Olympics.html infobox — link-only cells lost in extraction)",
    ],
    3: [
        "Mart Laar, Estonia",
        "Book: Free to Choose (Milton Friedman)",
        "Reform: introduction of the flat tax",
        "2006 Milton Friedman Prize for Advancing Liberty, awarded by the Cato "
        "Institute (Milton_Friedman.html, 'Estonia' subsection)",
    ],
    4: [
        "Falun (Sweden) and Lillehammer (Norway) tied 11–11 in round 4",
        "Run-off: Falun 41, Lillehammer 40",
        "Eliminated after round 1: Berchtesgaden (West Germany) "
        "(1992_Winter_Olympics.html bidding-results table)",
    ],
    5: [
        "'Known for' links to the SPI Group article",
        "Serene_(yacht).html links to Yuri Shefler (sold the yacht to Mohammed "
        "bin Salman for ~€500 million)",
    ],
}