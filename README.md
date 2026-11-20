# daily-facts

A free collection of surprising facts where **every fact has a source**, plus two Rainmeter desktop notes that show them.

The facts are Wikipedia's ["Did you know..."](https://en.wikipedia.org/wiki/Wikipedia:Did_you_know) hooks from 2021 onwards (from 2021 the reviews record the original source for most facts). Before a hook goes on Wikipedia's front page, a reviewer checks it against a cited source. For each fact this collection records:

- the Wikipedia article it comes from (always), and
- the original source named on its review page (a news article, book or paper), when one can be extracted.

## Using the data

Static JSON, served by GitHub Pages. No key, no rate limit beyond GitHub's normal fair use.

- `index.json` lists the months and how many facts each has.
- `facts/YYYY-MM.json` is an array of facts, one per line:

```json
{"id":"3f9a1c2e","text":"... that a Hungarian nobleman survived with a spear in his head?","date":"2025-10-31","article":"Portrait of Gregor Baci","article_url":"https://en.wikipedia.org/wiki/Portrait_of_Gregor_Baci","source_text":"Impaled head (2010)","source_url":"https://www.thelancet.com/...","source_citation":"..."}
```

| field | meaning |
|---|---|
| `id` | stable 8-character ID (first 8 hex chars of the SHA-1 of `text`) |
| `text` | the fact, in Wikipedia's "... that ...?" form |
| `date` | the day it appeared on Wikipedia's front page |
| `article`, `article_url` | the Wikipedia article it comes from |
| `source_text` | short name of the original source, e.g. `South China Morning Post (1965)`; empty if none was found |
| `source_url` | link to the original source; may be empty (books, paywalled newspapers) |
| `source_citation` | the fuller citation text, when available |

To get a random fact: download `index.json`, pick a month (weighted by `count`), download that month, and pick a line.

**License:** the facts are by Wikipedia contributors, under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Credit Wikipedia and keep the same license if you share them (see `docs/LICENSE-DATA.md`). The code is MIT.

## How it's built

`collector/collect.py` (Python 3, standard library only):

1. reads `Wikipedia:Did you know archive/<year>/<month>`;
2. cleans each hook's wiki markup;
3. finds the hook's review page (`Template:Did you know nominations/<article>`, or the one named on the article's talk page), matches the version of the hook that ran, and reads the `Source:` given for it;
4. writes `docs/facts/<month>.json` and `docs/index.json`.

It makes at most one request per second and caches every page in `collector/cache/` (not committed), so reruns are free.

```sh
python3 collector/collect.py 2021-01 2026-10   # a range of months
python3 collector/collect.py --last-month       # what the monthly job runs
python3 collector/collect.py --apply-hidden     # drop facts listed in hidden.txt
python3 -m unittest discover -s collector       # tests
```

A GitHub Action (`.github/workflows/collect.yml`) adds the previous month on the 2nd of each month, and re-publishes when `hidden.txt` changes.

**Hiding a fact:** put its ID (shown in the desktop note's tooltip) on its own line in `hidden.txt` and push.

## Desktop notes (Rainmeter, Windows)

- `FunFact/`: shows a random fact from this collection with its source, at the times set in `FetchTimes` (default 10:00 and 15:00). A missed time is caught up when the PC is next on, and restarting never refetches. Click the note to open the source. Set `BaseURL` to your GitHub Pages address.
- `OnThisDay/`: a random event from Wikipedia's "On this day" for today's date, refreshed every 2 hours.

Copy both folders into `Documents\Rainmeter\Skins\` and load them from the Rainmeter tray menu.
