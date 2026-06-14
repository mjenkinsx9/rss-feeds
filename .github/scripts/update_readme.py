#!/usr/bin/env python3
"""
Regenerate the "Available RSS Feeds" table in README.md from feeds.yaml.

Replaces whatever is between the <!-- FEEDS:START --> and <!-- FEEDS:END -->
markers with a table of every enabled (non-disabled) feed. Idempotent: only
rewrites README.md when the table actually changes. Run by the update-readme
workflow whenever feeds.yaml changes on main, and safe to run locally.
"""
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import generate  # noqa: E402  (for SITE_BASE_URL)

README = "README.md"
FEEDS = "feeds.yaml"
START = "<!-- FEEDS:START -->"
END = "<!-- FEEDS:END -->"


def cell(text):
    return str(text).replace("|", "\\|").strip()


def build_table(feeds):
    rows = ["| Source | Feed |", "| --- | --- |"]
    for c in feeds:
        if not isinstance(c, dict) or c.get("disabled") or not c.get("id"):
            continue
        fid = c["id"]
        title = c.get("title") or fid
        url = c.get("url", "")
        feed_url = "%s/%s.xml" % (generate.SITE_BASE_URL, fid)
        rows.append("| [%s](%s) | [%s.xml](%s) |" % (cell(title), cell(url), cell(fid), feed_url))
    if len(rows) == 2:
        rows.append("| _(no feeds yet)_ | |")
    return "\n".join(rows)


def main():
    with open(FEEDS, encoding="utf-8") as f:
        feeds = yaml.safe_load(f) or []
    with open(README, encoding="utf-8") as f:
        md = f.read()

    if START not in md or END not in md:
        sys.exit("::error::Markers %s / %s not found in %s" % (START, END, README))

    block = "%s\n%s\n%s" % (START, build_table(feeds), END)
    updated = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _m: block, md, flags=re.S)

    if updated != md:
        with open(README, "w", encoding="utf-8") as f:
            f.write(updated)
        print("README.md feed table updated.")
    else:
        print("README.md feed table already up to date.")


if __name__ == "__main__":
    main()
