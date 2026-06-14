"""
Example custom parser for sites that CSS selectors can't handle.

Reference it from feeds.yaml with:

    - id: tricky
      title: Tricky Site
      url: https://example.com/news
      recipe: example_recipe

`parse` receives the page HTML and the feed config dict, and must return a
list of dicts: {"title": str, "date": datetime|None, "link": str, "html": str}.
Use the helpers in generate.py (clean_body, abs_url, parse_date) if useful.
"""
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import generate as g


def parse(html_text, cfg):
    soup = BeautifulSoup(html_text, "html.parser")
    items = []
    for el in soup.select("article"):          # <- customise this
        h = el.find(["h1", "h2", "h3"])
        if not h:
            continue
        title = h.get_text(" ", strip=True)
        link = g.abs_url((el.find("a") or {}).get("href"), cfg["url"]) if el.find("a") else cfg["url"]
        date = None                            # parse a date if the page has one
        body = g.clean_body(el, cfg["url"])
        items.append({"title": title, "date": date, "link": link, "html": body})
    return items
