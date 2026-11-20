#!/usr/bin/env python3
"""Collect Wikipedia "Did you know..." facts, with their sources, into static JSON for GitHub Pages.

Usage:
  collect.py 2015-01 2025-10     collect a range of months (inclusive)
  collect.py --last-month        collect the previous calendar month (used by the monthly GitHub Action)
  collect.py --apply-hidden      drop facts listed in hidden.txt from the published files (no network)

Output: docs/facts/YYYY-MM.json (one fact per line) and docs/index.json.
Facts are Wikipedia content: CC BY-SA 4.0, attribution to Wikipedia (see docs/LICENSE-DATA.md).
"""
import datetime
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CACHE = Path(__file__).resolve().parent / "cache"
HIDDEN = ROOT / "hidden.txt"
USER_AGENT = "daily-facts/0.1 (https://github.com/raditya-rizky/daily-facts; one request per second)"
WIKI = "https://en.wikipedia.org"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# ---------------------------------------------------------------- wikitext cleaning

APOS = "\x01"

# simple templates: name -> function(positional params) -> text
TEMPLATES = {
    # APOS instead of "'" so the apostrophe survives stripping of the italic/bold quote marks next to it
    "'": lambda p: APOS, "'s": lambda p: APOS + "s", "`s": lambda p: APOS + "s", "`": lambda p: APOS, "-'": lambda p: APOS,
    "-?": lambda p: "?", "snd": lambda p: " – ", "spaced ndash": lambda p: " – ",
    "ndash": lambda p: "–", "mdash": lambda p: "—", "nbsp": lambda p: " ", "sic": lambda p: "",
    "nowrap": lambda p: p[0] if p else "", "nobr": lambda p: p[0] if p else "", "em": lambda p: p[0] if p else "",
    "lang": lambda p: p[1] if len(p) > 1 else "", "transl": lambda p: p[-1] if p else "",
    "transliteration": lambda p: p[-1] if p else "", "abbr": lambda p: p[0] if p else "",
    "ill": lambda p: p[0] if p else "", "interlanguage link": lambda p: p[0] if p else "",
    "frac": lambda p: "/".join(p) if len(p) < 3 else f"{p[0]} {p[1]}/{p[2]}",
    "convert": lambda p: f"{p[0]} {p[1]}" if len(p) > 1 and p[1] not in ("-", "to", "and", "–") else
    (f"{p[0]}–{p[2]} {p[3]}" if len(p) > 3 else ""),
    "cvt": lambda p: f"{p[0]} {p[1]}" if len(p) > 1 else "",
    "small": lambda p: p[0] if p else "", "smallcaps": lambda p: p[0] if p else "", "script": lambda p: p[-1] if p else "",
    "nihongo": lambda p: p[0] if p else "", "korean": lambda p: p[0] if p else "", "zh": lambda p: "",
    "as of": lambda p: "as of " + " ".join(p), "circa": lambda p: "c. " + (p[0] if p else ""),
    "c.": lambda p: "c. " + (p[0] if p else ""), "angbr": lambda p: f"⟨{p[0]}⟩" if p else "",
    "pictured": lambda p: "", "ship": lambda p: " ".join(x for x in p[:2] if x), "sclass": lambda p: p[0] if p else "",
    "math": lambda p: p[0] if p else "", "mvar": lambda p: p[0] if p else "", "var": lambda p: p[0] if p else "",
    "dollar sign": lambda p: "$", "us$": lambda p: "US$" + (p[0] if p else ""), "inflation": None,
}


def split_params(body):
    """Split a template body on top-level '|' (ignores pipes inside [[...]] and {{...}})."""
    parts, depth, cur = [], 0, ""
    i = 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("[[", "{{"):
            depth += 1; cur += two; i += 2; continue
        if two in ("]]", "}}"):
            depth -= 1; cur += two; i += 2; continue
        if body[i] == "|" and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += body[i]
        i += 1
    parts.append(cur)
    return parts


def _expand_templates(s):
    """Replace innermost {{...}} repeatedly. Returns None if an unknown template is found."""
    pat = re.compile(r"\{\{([^{}]*)\}\}")
    while True:
        m = pat.search(s)
        if not m:
            return s
        parts = split_params(m.group(1))
        name = parts[0].strip().lower()
        fn = TEMPLATES.get(name)
        if fn is None:
            return None
        positional = [p.strip() for p in parts[1:] if "=" not in p]
        s = s[:m.start()] + fn(positional) + s[m.end():]


def clean(s):
    """Wikitext -> plain text. Returns None when the text holds markup we don't understand."""
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", s, flags=re.S | re.I)
    s = re.sub(r"\s*'*\([^()]*\b(?:pictured|illustrated|depicted|shown|left|right|center|centre)\b[^()]*\)'*", "", s)
    s = _expand_templates(s)
    if s is None:
        return None
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)        # [[A|b]] -> b, [[A]] -> A
    s = re.sub(r"\[(?:https?:)?//[^\s\]]+\s+([^\]]*)\]", r"\1", s)  # [url label] -> label
    s = re.sub(r"\[(?:https?:)?//[^\s\]]+\]", "", s)                # [url] -> ''
    s = re.sub(r"'{2,}", "", s).replace(APOS, "'")
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([?,.;:!])", r"\1", s)
    if re.search(r"\{\{|\}\}|\[\[|\]\]|<|>", s):
        return None
    return s


def ucfirst(title):
    return title[:1].upper() + title[1:]


def wiki_url(title):
    return f"{WIKI}/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="()_,'!:")


# ---------------------------------------------------------------- archive parsing

HOOK_RE = re.compile(r"^\*\s*\.\.\.\s*that\b")
BOLD_LINK_RE = re.compile(r"'{3,5}\[\[([^\]|#]+)")
DAY_RE = re.compile(r"^=+\s*(\d{1,2} [A-Z][a-z]+ \d{4})\s*=+\s*$")


def parse_archive(wikitext):
    """Return [{date, text, article, article_url}] for each hook in a monthly DYK archive page."""
    facts, date = [], ""
    for line in wikitext.splitlines():
        line = line.strip()
        m = DAY_RE.match(line)
        if m:
            date = datetime.datetime.strptime(m.group(1), "%d %B %Y").date().isoformat()
            continue
        if not HOOK_RE.match(line):
            continue
        link = BOLD_LINK_RE.search(line)
        text = clean(line.lstrip("* "))
        if not link or not text or not text.startswith("... that"):
            continue
        article = ucfirst(link.group(1).strip().replace("_", " "))
        facts.append({"date": date, "text": text, "article": article, "article_url": wiki_url(article)})
    return facts


# ---------------------------------------------------------------- sources

GENERIC_LABELS = {"source", "here", "link", "this", "article", "website", "web", "online", "pdf", "url", "1", "2"}
SOURCE_RE = re.compile(r"Source\s*:?\s*'*\s*:?\s*(.*)", re.I)
YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
WORK_KEYS = ("work", "website", "newspaper", "journal", "magazine", "periodical", "publisher", "via", "agency")


def _domain(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _with_year(name, year):
    return f"{name} ({year})" if year else name


def short_source(raw):
    """Source wikitext -> (short display text, url, cleaned citation). Empty strings when nothing usable."""
    raw = re.sub(r"</?small>", "", raw).strip()
    raw = re.sub(r"\}\}\s*$", "", raw) if raw.count("}}") > raw.count("{{") else raw
    raw = raw.strip()
    if not raw:
        return "", "", ""

    cite = re.search(r"\{\{\s*cite[ _]\w+", raw, re.I)
    if cite:
        # find the matching close of this cite template
        depth, i = 0, cite.start()
        while i < len(raw):
            if raw.startswith("{{", i):
                depth += 1; i += 2; continue
            if raw.startswith("}}", i):
                depth -= 1; i += 2
                if depth == 0:
                    break
                continue
            i += 1
        body = raw[cite.start() + 2:i - 2]
        params = {}
        for p in split_params(body)[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k.strip().lower()] = v.strip()
        url = params.get("url", "")
        if not url.startswith("http"):
            url = ""
        work = next((params[k] for k in WORK_KEYS if params.get(k)), "")
        title = params.get("title", "") or params.get("chapter", "")
        y = YEAR_RE.search(params.get("date", "") or params.get("year", "") or params.get("publication-date", ""))
        year = y.group(1) if y else ""
        name = clean(work) or clean(title) or (_domain(url) if url else "")
        citation = ". ".join(x for x in (clean(title) or "", clean(work) or "", year) if x)
        if not name:
            return "", "", ""
        return _with_year(name, year), url, citation

    m = re.search(r"\[(https?://[^\s\]]+)(?:\s+([^\]]*))?\]", raw)
    bare = re.search(r"https?://[^\s\]|}<\"]+", raw)
    url = m.group(1) if m else (bare.group(0) if bare else "")
    label = (clean(m.group(2) or "") or "") if m else ""
    citation = (clean(raw) or "")[:400]
    years = re.search(r"\((1[5-9]\d\d|20\d\d)[a-z]?\)", raw)
    year = years.group(1) if years else ""

    if not url and not year and raw[:1] in "\"“'«„‘":
        return "", "", ""  # just a quote, no citation
    if raw.startswith("http") and not m:
        return _domain(url), url, url

    book = re.match(r"^(.+?)\((1[5-9]\d\d|20\d\d)[a-z]?\)\.\s*(.+?)\.(?:\s|$)", raw)
    if book:
        title = (clean(book.group(3)) or "").strip("\"“”' ")
        if title:
            return _with_year(title[:90], year), url, citation
    label = re.sub(r"^www\.", "", label)
    if label and 1 < len(label) <= 60 and label.lower() not in GENERIC_LABELS:
        return _with_year(label, year), url, citation
    if url:
        return _with_year(_domain(url), year), url, citation
    if citation:
        return citation[:60], "", citation
    return "", "", ""


def _words(s):
    return set(re.findall(r"[a-z0-9]+", s.lower())) - {"that", "the", "a", "an", "of", "in", "and", "to", "was", "is"}


def find_source(nom_wikitext, hook_text):
    """Find the source given for the hook that actually ran, on its nomination page."""
    lines = nom_wikitext.splitlines()
    target = _words(hook_text)
    best, best_score = -1, 0.0
    for i, line in enumerate(lines):
        if "... that" not in line:
            continue
        hook_part = re.split(r"<small>|Source\s*:", line, flags=re.I)[0]
        if "... that" not in hook_part or "<s>" in hook_part:  # quoted in a comment, or struck out
            continue
        cleaned = clean(hook_part[hook_part.index("... that"):]) or hook_part
        score = len(target & _words(cleaned)) / max(1, len(target))
        if score >= best_score and score > 0:  # ties: later lines are the revised versions that ran
            best, best_score = i, score
    if best < 0 or best_score < 0.6:
        return "", "", ""

    inline = re.search(r"Source\s*:?\s*(.*)", lines[best].split("... that", 1)[1], re.I)
    if inline and inline.group(1).strip():
        return short_source(inline.group(1))
    for line in lines[best + 1:best + 6]:
        if "... that" in line:
            break
        m = re.match(r"^[*:#\s]*(?:'''|<small>)?\s*" + SOURCE_RE.pattern, line, re.I)
        if m:
            return short_source(m.group(1))
    return "", "", ""


def fact_id(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def apply_hidden(facts, hidden):
    return [f for f in facts if f["id"] not in hidden]


# ---------------------------------------------------------------- network (cached, 1 req/s)

_last_request = 0.0


def fetch_raw(title):
    """Raw wikitext of a page, or '' if it doesn't exist. Cached on disk so reruns are free."""
    global _last_request
    path = CACHE / (hashlib.sha1(title.encode()).hexdigest() + ".txt")
    if path.exists():
        return path.read_text(encoding="utf-8")
    url = f"{WIKI}/w/index.php?" + urllib.parse.urlencode({"title": title, "action": "raw"})
    for attempt in range(5):
        wait = 1.0 - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            text = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                text = ""
                break
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"giving up on {title}")
    CACHE.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def nomination_page(article):
    """Wikitext of the DYK nomination for an article; falls back to the nompage named on its talk page."""
    text = fetch_raw(f"Template:Did you know nominations/{article}")
    if text.lstrip().upper().startswith("#REDIRECT"):
        m = re.search(r"\[\[([^\]|]+)", text)
        text = fetch_raw(m.group(1)) if m else ""
    if text:
        return text
    talk = fetch_raw(f"Talk:{article}")
    m = re.search(r"\|\s*nompage\s*=\s*([^|}\n]+)", talk)
    return fetch_raw(m.group(1).strip()) if m else ""


# ---------------------------------------------------------------- output

def load_hidden():
    if not HIDDEN.exists():
        return set()
    return {line.split("#")[0].strip() for line in HIDDEN.read_text().splitlines() if line.split("#")[0].strip()}


def write_month(month, facts):
    out = DOCS / "facts" / f"{month}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in facts]
    out.write_text("[\n" + ",\n".join(lines) + "\n]\n", encoding="utf-8")


def write_index():
    months = []
    for p in sorted((DOCS / "facts").glob("*.json")):
        count = len(json.loads(p.read_text(encoding="utf-8")))
        if count:
            months.append({"month": p.stem, "count": count})
    index = {
        "months": months,
        "total": sum(m["count"] for m in months),
        "license": "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)",
        "attribution": "Facts from Wikipedia's \"Did you know...\" archive (https://en.wikipedia.org/wiki/Wikipedia:Did_you_know), "
                       "by Wikipedia contributors.",
    }
    (DOCS / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def collect_month(month, hidden):
    year, mon = map(int, month.split("-"))
    wikitext = fetch_raw(f"Wikipedia:Did you know archive/{year}/{MONTHS[mon - 1]}")
    if wikitext.lstrip().upper().startswith("#REDIRECT"):
        m = re.search(r"\[\[([^\]|]+)", wikitext)
        wikitext = fetch_raw(m.group(1)) if m else ""
    facts, seen = [], set()
    for f in parse_archive(wikitext):
        fid = fact_id(f["text"])
        if fid in seen:
            continue
        seen.add(fid)
        nom = nomination_page(f["article"])  # network errors still stop the run (rerun resumes from cache)
        try:
            short, url, citation = find_source(nom, f["text"])
        except Exception as e:  # odd markup in one review page: keep the fact, Wikipedia article as its source
            print(f"  source parse failed for {f['article']!r}: {e!r}", flush=True)
            short, url, citation = "", "", ""
        facts.append({"id": fid, "text": f["text"], "date": f["date"], "article": f["article"],
                      "article_url": f["article_url"], "source_text": short, "source_url": url,
                      "source_citation": citation})
    facts = apply_hidden(facts, hidden)
    write_month(month, facts)
    sourced = sum(1 for f in facts if f["source_text"])
    print(f"{month}: {len(facts)} facts, {sourced} with an original source", flush=True)


def month_range(start, end):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main(argv):
    hidden = load_hidden()
    if argv == ["--apply-hidden"]:
        for p in sorted((DOCS / "facts").glob("*.json")):
            facts = json.loads(p.read_text(encoding="utf-8"))
            kept = apply_hidden(facts, hidden)
            if len(kept) != len(facts):
                write_month(p.stem, kept)
                print(f"{p.stem}: hid {len(facts) - len(kept)}")
    elif argv == ["--last-month"]:
        first = datetime.date.today().replace(day=1)
        last = first - datetime.timedelta(days=1)
        collect_month(f"{last.year:04d}-{last.month:02d}", hidden)
    elif len(argv) == 2:
        for month in month_range(*argv):
            collect_month(month, hidden)
    else:
        print(__doc__)
        return 2
    write_index()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
