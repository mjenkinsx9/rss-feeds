# rss-feeds

A tiny, config-driven **RSS factory**. Describe any web page in `feeds.yaml`
using CSS selectors, and a GitHub Action rebuilds an RSS 2.0 feed for each one
every few hours and publishes them to GitHub Pages. No server to run.

- **Feeds list / landing page:** `https://mjenkinsx9.github.io/rss-feeds/`
- **Per-feed URL:** `https://mjenkinsx9.github.io/rss-feeds/<id>.xml`
  (e.g. `.../codex.xml`)

Ships with one working feed (the OpenAI Codex changelog) plus example templates.

---

## One-time setup

1. **Create the repo.** On GitHub (`mjenkinsx9`), make a new **public** repo
   named **`rss-feeds`** and push this folder (keep the structure):

   ```bash
   git init
   git add .
   git commit -m "RSS factory"
   git branch -M main
   git remote add origin https://github.com/mjenkinsx9/rss-feeds.git
   git push -u origin main
   ```

2. **Enable Pages.** Settings → Pages → Source: **GitHub Actions**.

3. **Run it once.** Actions tab → "Build RSS feeds" → **Run workflow**.

Your feeds are then live. Subscribe by pasting a feed URL into any reader
(Feedly, Inoreader, NetNewsWire, Thunderbird, …).

---

## Adding a new site

Edit **`feeds.yaml`** and add an entry. Open the target page, right-click an
entry → **Inspect**, and find CSS selectors for the repeating item, its title,
date, and body.

```yaml
- id: my-site                 # -> docs/my-site.xml
  title: My Site Updates
  url: https://my-site.com/news
  item: "article.post"        # selector matching ONE entry
  entry_title: "h2 a"         # title, within an item
  body: ".summary"            # description HTML, within an item
  date:
    selector: "time"
    attr: "datetime"          # ISO date in an attribute...
    # format: "%b %d, %Y"     # ...or strptime format if it's plain text
    # regex: '20\d{2}-\d{2}-\d{2}'   # ...or pull a date out of the item text
  link:
    selector: "h2 a"
    attr: "href"
    # base_anchor: true       # or: link = page url + '#' + slug(title)
  max_items: 50
```

Commit and push — the Action rebuilds everything. Run `python generate.py`
locally first if you want to preview.

### Field reference

| field | meaning |
|-------|---------|
| `id` | slug; output is `docs/<id>.xml` |
| `title` | feed title |
| `url` | page to scrape |
| `item` | CSS selector matching one entry (**required**) |
| `entry_title` | selector for the headline (omit = use item text) |
| `body` | selector for the description HTML |
| `date.selector` / `date.attr` | where to read the date; `attr` reads an attribute |
| `date.format` | `strptime` format if the date isn't ISO |
| `date.regex` | pull a date from the item's text instead |
| `link.selector` / `link.attr` | where to read the item link |
| `link.base_anchor` | `true` → link = `url#slug(title)` |
| `max_items` | cap the item count |
| `disabled` | `true` → skip this feed |
| `recipe` | use a custom parser in `recipes/` (see below) |

## Sites selectors can't handle

Some pages need real logic (odd markup, combining fields, etc.). Drop a Python
module in `recipes/` that exports `parse(html, cfg)` returning a list of
`{"title", "date", "link", "html"}` dicts, then reference it:

```yaml
- id: tricky
  title: Tricky Site
  url: https://example.com
  recipe: example_recipe      # -> recipes/example_recipe.py
```

See `recipes/example_recipe.py` for a starting point.

## Notes & limits

- The Action uses a plain HTTP fetch, so it reads the page's **server-rendered
  HTML**. Pages that build their entire list with client-side JavaScript may
  return nothing — for those, use a service like RSS.app, or add a headless
  browser (Playwright) step to the workflow.
- A broken feed logs an error but does **not** fail the whole run; the other
  feeds still publish.
- Change the schedule via the `cron:` line in `.github/workflows/build.yml`.
- If you rename the repo, update `SITE_BASE_URL` near the top of `generate.py`.

## Run locally

```bash
pip install -r requirements.txt
python generate.py      # writes docs/<id>.xml and docs/index.html
```

## Disclaimer

This project only reformats publicly available pages into RSS. It is not
affiliated with or endorsed by the sites it indexes; their content remains
theirs.
