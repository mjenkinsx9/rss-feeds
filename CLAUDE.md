# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A config-driven "RSS factory." A single generic engine (`generate.py`) reads
`feeds.yaml`, scrapes each described web page with CSS selectors, and writes an
RSS 2.0 file to `docs/<id>.xml` plus a landing page `docs/index.html`. A GitHub
Action rebuilds everything on a schedule and publishes `docs/` to GitHub Pages.
There is no server and no database — the only persistent state is the generated
files under `docs/`.

## Commands

```bash
pip install -r requirements.txt
python generate.py        # rebuild every enabled feed into docs/<id>.xml + docs/index.html
```

There is no test suite, linter, or build step. To "test" a change, run
`python generate.py` and inspect the regenerated files in `docs/`. The script
prints one `[ok]`/`[ERR]` line per feed and a final summary.

To work on a single feed without rebuilding all of them, set `disabled: true`
on the others in `feeds.yaml` (the loop skips disabled entries).

## Architecture

The whole engine is `generate.py`, structured as a pipeline of small pure-ish
functions feeding `build_feed()`:

- `main()` — loads `feeds.yaml`, skips entries with `disabled: true`, calls
  `build_feed()` per feed, then `write_index()`. **Always exits 0**: a failing
  site is logged to stderr but never fails the run, so the other feeds still
  publish. Preserve this fail-soft behavior unless explicitly asked to change it.
- `build_feed(cfg)` — fetches the page (plain `requests.get`, no JS rendering),
  dispatches to either `parse_with_selectors()` or a custom recipe, sorts items
  newest-first only when *all* items have dates (otherwise keeps document order),
  caps to `max_items`, and serializes RSS by **string templating** (not an XML
  library). Descriptions are wrapped in `<![CDATA[...]]>`; other fields are
  `html.escape`d.
- `parse_with_selectors(html, cfg)` — the default path. Iterates `cfg["item"]`
  matches and pulls title/date/link/body via the `extract_*` helpers, deduping
  on `(title, date)`.
- Helpers: `extract_date` (selector→attr, selector→text, or regex-over-item-text,
  with optional strptime `format`), `extract_link` (selector/attr or
  `base_anchor` → `url#slug(title)`), `clean_body` (sanitizes HTML to a small
  allowlist `KEEP`, drops `DROP` tags, demotes h1–h3 to h4, absolutizes links),
  `abs_url`, `slug`.

### Two ways to define a feed

1. **CSS selectors in `feeds.yaml`** — the normal case. The field reference is
   documented both in `feeds.yaml`'s header comment and `README.md`.
2. **A recipe module** — for pages selectors can't express. Set
   `recipe: <module>` in the feed entry; the engine imports `recipes.<module>`
   and calls `parse(html_text, cfg)`, which must return a list of
   `{"title", "date" (datetime|None), "link", "html"}` dicts. Recipes import
   `generate` as a module to reuse `clean_body`, `abs_url`, `parse_date`. See
   `recipes/example_recipe.py`.

### Feed-request bot (issue → moderated PR)

Users can request a feed by opening an issue
(`.github/ISSUE_TEMPLATE/request-feed.yml`, which auto-applies the `feed-request`
label). `.github/workflows/feed-request.yml` then runs
`.github/scripts/process_feed_request.py`, which:

1. Parses the issue-form body and validates the basics (URL, title, policy
   checkbox).
2. Fetches the page and asks **Claude** (`claude-haiku-4-5` — chosen via
   `.github/scripts/benchmark_models.py` as the cheapest model that passed; via
   the `anthropic` SDK with **structured outputs**) to do two things at once:
   moderate against `CONTENT_POLICY.md` and derive the CSS selectors. Haiku
   doesn't support adaptive thinking, so no `thinking` param is sent.
3. On **approve**: appends an entry to `feeds.yaml` (by appending a
   `yaml.safe_dump` block — it does *not* re-dump the whole file, so the header
   comments and disabled examples are preserved), verifies by calling
   `generate.build_feed(cfg)` once, and the workflow opens a PR. On **reject**:
   comments + closes. On **needs_info**: comments + labels.

The script never calls `gh`/`git` itself — it sets step outputs (`decision`,
`branch`, `slug`, …) and writes `.bot_out/issue_comment.md` + `.bot_out/pr_body.md`;
the workflow does all GitHub mutations. **Every approval is a PR a human merges**
— Claude's selectors are a proposal, never auto-published.

A second workflow, `.github/workflows/feed-request-close.yml`, fires on
`pull_request: [closed]` and closes the linked issue when its PR is merged or
closed. On merge GitHub already auto-closes it via the `Closes #N` in the PR
body; this workflow covers the close-without-merge case (and is idempotent on
merge). It recovers the issue number from the numeric suffix of the
`feed-request/<slug>-<n>` branch name.

Key facts for working on this:
- The issue body and scraped HTML are **untrusted**. The system prompt in
  `process_feed_request.py` treats them as data-only and forbids following
  instructions inside them; the JSON-schema output bounds the result. Preserve
  this if you edit the prompt.
- Requires the **`ANTHROPIC_API_KEY`** repo secret (small per-issue API cost).
- Needs **"Allow GitHub Actions to create and approve pull requests"** enabled
  (repo Settings → Actions → General, or the
  `actions/permissions/workflow` API) so the default `GITHUB_TOKEN` can open the
  PR.
- The script's deps are in `.github/scripts/requirements.txt` (adds `anthropic`);
  the engine's `requirements.txt` is kept dependency-light and unchanged.

### PR checks

`.github/workflows/validate-feeds.yml` runs
`.github/scripts/validate_feeds.py` on PRs that touch `feeds.yaml` (or the engine).
It always does structural + duplicate validation (unique slug-form `id`,
required fields, valid `date`/`link`/`max_items` shapes, recipe module exists,
duplicate-url warning) and **fails the PR on any error**. When the base
`feeds.yaml` is passed (the workflow supplies it via `git show FETCH_HEAD`), it
also **smoke-builds only the newly added feeds** against the live page — 0 items
is an error, 1–2 a warning. This is the real gate on `main`: it re-checks for
duplicate ids at *merge* time (the bot only checked at issue-open time) and
verifies selectors still work.

### Deployment

`.github/workflows/build.yml` runs `python generate.py` every 6 hours (and on
push to `main` / manual dispatch) and deploys `docs/` to GitHub Pages. Change
the cadence via the `cron:` line there.

## Gotchas

- **`SITE_BASE_URL` in `generate.py`** (and the repo URLs in `README.md`) are
  hardcoded to `mjenkinsx9/rss-feeds`. If the repo is renamed or moved, update
  `SITE_BASE_URL` — it's only used for the `atom:self` link and per-feed URLs.
- **JS-rendered pages return nothing.** The fetch reads server-rendered HTML
  only. If a selector that looks correct yields zero items, the content is
  likely client-rendered — that's not a selector bug.
- **Nested duplicate tree.** `rss-feeds/rss-feeds/` contains a byte-identical
  copy of the project (same `generate.py`, `feeds.yaml`, `docs/`, etc.). It
  appears accidental. The live project is the repo root; make edits there, not
  in the nested copy. Confirm with the user before touching or deleting the
  nested copy.
- This is not yet a git repository (`git init` is part of the one-time setup in
  `README.md`).
