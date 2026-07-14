#!/usr/bin/env python3
"""

METHOD
Every suspension in this dataset is stated in the narrative as a number
(spelled out, digit, or "word (digit)") immediately before "suspension" or,
in a few records that drop that word, before "without pay". Two patterns
catch that, in either "day" or "workday" units (both counted together,
undifferentiated, matching how this chart has always presented them):

  PAT_SUSPENSION   "<word>? (<digit>)? <unit> suspension"
                   e.g. "twenty-one (21) workday suspension", "five-day
                   suspension", "30-day suspension"
  PAT_WITHOUTPAY   same, ending "... without pay" instead of "suspension"

A hearing's narrative often recaps the officer's PRIOR suspensions too, in
an "active discipline history (...)" parenthetical (and sometimes again in
an "aggravating factors (active discipline: ...)" gloss) — those are
excluded by (a) discarding any candidate found inside a parenthetical that
contains a date or the phrase "discipline history", (b) discarding a
candidate that's the second half of a "5 to 10-day suspension" policy-matrix
range, and (c) discarding any candidate followed by text indicating the
suspension shown isn't the final outcome ("is rescinded", "was terminated",
"grieved ... reinstruction", etc.) via OVERRIDE_MARKERS. What's left is
read in text order, and the LAST surviving candidate is taken as the
current hearing's actual outcome, since prior-case recaps are always stated
before it.

VALIDATED against the suspension_days/suspension_unit columns that used to
live in cpd_data_with_suspension.csv (a manually-built enrichment with no
script of its own): this reproduces 782 of 786 rows exactly. The other 4
are cases where this script is right and that column was wrong — see the
4 CASE_NOTES below, each with the specific text that supports it.

Setup:
  - Put cpd_data.csv next to this file (or edit CSV_PATH).

Run:
  python3 build_data.py
"""

import csv
import re
from collections import Counter
from pathlib import Path

HERE       = Path(__file__).parent
INDEX_HTML = HERE / "index.html"
CSV_PATH   = HERE / "cpd_data.csv"

CASE_NOTES = {
    "1642": 'Text says "the two-day suspension is rescinded" and Decision '
            'type is "dismissal", not "suspension" — it was never served, '
            "so it's excluded here (the old column counted it as 2 days).",
    "605":  'Text says "received a fifteen (15) workday without pay" — a '
            "real suspension the old column missed entirely (it omits the "
            'word "suspension").',
    "812":  'Text says "received a twenty five (25) workday suspension '
            'without pay" — the only number in the record. The old column '
            "had 5, not 25.",
    "820":  'Same pattern as 812 — "a twenty five (25) workday suspension '
            'without pay" is the only number present. The old column had '
            "5, not 25.",
}

ONES = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
        "ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,
        "sixteen":16,"seventeen":17,"eighteen":18,"nineteen":19}
TENS = {"twenty":20,"thirty":30,"forty":40}

def word_to_num(s):
    s = re.sub(r"\s+", " ", s.lower().strip())
    if s in ONES: return ONES[s]
    if s in TENS: return TENS[s]
    m = re.match(r"(twenty|thirty|forty)[-\s]+(\w+)$", s)
    if m and m.group(2) in ONES:
        return TENS[m.group(1)] + ONES[m.group(2)]
    return None

_ones_alt = "|".join(ONES.keys())
_tens_alt = "|".join(TENS.keys())
# Real number words only (so "five-day" doesn't get swallowed whole with
# nothing left for the unit group), tens+ones joined by hyphen OR space
# (source text has both "twenty-five" and "twenty five", plus PDF-copy
# line-wrap artifacts like "twenty-\nfive" -> "twenty- five" after
# whitespace collapsing).
WORDNUM = rf"(?:(?:{_tens_alt})[-\s]+(?:{_ones_alt})|{_tens_alt}|{_ones_alt})"
UNIT = r"(?:calendar\s*day|work\s*day|day)"
SEP = r"[-\s]*"  # hyphen/space mix between number and unit

PAT_SUSPENSION = re.compile(
    rf"\b(?P<word>{WORDNUM})?{SEP}(?:\((?P<paren>\d+)\)|(?P<digit>\d+))?{SEP}(?P<unit>{UNIT})s?\s+suspension\b",
    re.I,
)
PAT_WITHOUTPAY = re.compile(
    rf"\b(?P<word>{WORDNUM})?{SEP}(?:\((?P<paren>\d+)\)|(?P<digit>\d+))?{SEP}(?P<unit>{UNIT})s?\s+without\s+pay\b",
    re.I,
)

TRAIL_WINDOW = 160

OVERRIDE_MARKERS = re.compile(
    r"held from previous discipline|previous discipline imposed|held in abeyance"
    r"|is rescinded|was rescinded"
    r"|grieved.{0,150}?(reinstruction|dismiss)"
    r"|overturned|vacated"
    r"|terminated",
    re.I,
)

PAREN_SPAN_PAT = re.compile(r"\([^()]*\)")
DATE_IN_PAREN_PAT = re.compile(r"\d{1,2}/\d{1,2}/(?:20)?\d{2}")
RANGE_PREFIX_PAT = re.compile(r"\bto\s*$", re.I)

def unit_key(u):
    u = re.sub(r"\s+", "", u.lower())
    return "workday" if u == "workday" else "day"

def history_spans(text):
    """Parenthetical spans that recap a PRIOR case, not this hearing's own outcome."""
    spans = []
    for m in PAREN_SPAN_PAT.finditer(text):
        if DATE_IN_PAREN_PAT.search(m.group(0)) or "discipline history" in m.group(0).lower():
            spans.append((m.start(), m.end()))
    return spans

def extract_candidates(text):
    text = re.sub(r"\s+", " ", text)  # embedded newlines break `.` in the regexes below
    spans = history_spans(text)
    out = []
    for pat in (PAT_SUSPENSION, PAT_WITHOUTPAY):
        for m in pat.finditer(text):
            days = None
            if m.group("paren"):
                days = int(m.group("paren"))
            elif m.group("digit"):
                days = int(m.group("digit"))
            elif m.group("word"):
                days = word_to_num(m.group("word"))
            if days is None:
                continue
            if any(s0 <= m.start() < s1 for s0, s1 in spans):
                continue  # inside a prior-case recap parenthetical
            if RANGE_PREFIX_PAT.search(text[max(0, m.start() - 20):m.start()]):
                continue  # "N to M day suspension" policy-matrix range
            trailing = text[m.end(): m.end() + TRAIL_WINDOW]
            out.append((m.start(), m.end(), days, unit_key(m.group("unit")), trailing))
    out.sort(key=lambda x: x[0])
    deduped = []
    last_end = -1
    for c in out:
        if c[0] >= last_end:
            deduped.append(c)
            last_end = c[1]
    return deduped

def parse_suspension_days(text):
    cands = extract_candidates(text)
    live = [c for c in cands if not OVERRIDE_MARKERS.search(c[4])]
    # Prior cases are always recapped before the current hearing's own
    # outcome, so the last surviving candidate is the current one.
    chosen = live[-1] if live else None
    return (chosen[2], chosen[3]) if chosen else (None, None)

# ── Parse every row ───────────────────────────────────────────────────────────

hist = Counter()

with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        days, unit = parse_suspension_days(row.get("Charge & Discipline Decision") or "")
        if days is None:
            continue
        hist[days] += 1

total = sum(hist.values())

# ── Write back into index.html ───────────────────────────────────────────────

raw_html = INDEX_HTML.read_text(encoding="utf-8")

entries = ",\n".join(f"      {{ days: {d}, count: {hist[d]} }}" for d in sorted(hist))
data_js = f"const data = [\n{entries},\n    ];"

new_html, n = re.subn(r"const data = \[.*?\];", data_js, raw_html, count=1, flags=re.DOTALL)
if n == 0:
    raise RuntimeError("Could not find 'const data = [...];' in index.html")

new_html, n2 = re.subn(r"const TOTAL\s*=\s*\d+;", f"const TOTAL     = {total};", new_html, count=1)
if n2 == 0:
    raise RuntimeError("Could not find 'const TOTAL = ...;' in index.html")

INDEX_HTML.write_text(new_html, encoding="utf-8")

print(f"Updated {INDEX_HTML.name} — {total} suspensions across {len(hist)} distinct lengths.")
for d in sorted(hist):
    print(f"  {d} day(s): {hist[d]}")
