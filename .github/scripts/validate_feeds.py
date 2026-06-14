#!/usr/bin/env python3
"""
Validate feeds.yaml and smoke-build newly added feeds. Used as a PR check.

Always run (structural + duplicate checks):
  - feeds.yaml is a YAML list of mappings
  - each feed has id/title/url and item (item optional when `recipe` is set)
  - id is a clean slug and is UNIQUE
  - date/link are mappings with only known keys; max_items is a positive int;
    a referenced recipe module exists
  - duplicate urls are flagged (warning)

Quality gate (when a base feeds.yaml is passed as argv[1]):
  - for every feed added vs the base, fetch the page and build it once;
    0 items is an error (selectors don't match), 1-2 is a warning.

Exit code is non-zero if there are any errors; warnings don't fail the build.
Emits GitHub Actions ::error:: / ::warning:: annotations.
"""
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import generate  # noqa: E402

FEEDS = "feeds.yaml"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TOP_KEYS = {"id", "title", "url", "item", "entry_title", "body", "date", "link",
            "description", "max_items", "disabled", "recipe"}
DATE_KEYS = {"selector", "attr", "regex", "format"}
LINK_KEYS = {"selector", "attr", "base_anchor"}


def load(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    if not isinstance(data, list):
        raise SystemExit("::error::feeds.yaml must be a YAML list")
    return data


def main():
    base_path = sys.argv[1] if len(sys.argv) > 1 else None
    feeds = load(FEEDS)
    errors, warnings = [], []
    ids, urls = {}, {}

    for i, cfg in enumerate(feeds):
        where = "entry #%d" % (i + 1)
        if not isinstance(cfg, dict):
            errors.append("%s: is not a mapping" % where)
            continue
        fid = cfg.get("id")
        where = "'%s'" % fid if fid else where

        for key in ("id", "title", "url"):
            if not cfg.get(key):
                errors.append("%s: missing required field '%s'" % (where, key))
        if not cfg.get("item") and not cfg.get("recipe"):
            errors.append("%s: missing 'item' (required unless 'recipe' is set)" % where)

        if fid:
            if not SLUG_RE.match(str(fid)):
                errors.append("%s: id must be lowercase letters, numbers and hyphens" % where)
            if fid in ids:
                errors.append("%s: duplicate id (also entry #%d)" % (where, ids[fid] + 1))
            else:
                ids[fid] = i

        url = cfg.get("url")
        if url:
            if url in urls:
                warnings.append("%s: duplicate url, same page as '%s'"
                                % (where, feeds[urls[url]].get("id")))
            else:
                urls[url] = i

        extra = set(cfg) - TOP_KEYS
        if extra:
            warnings.append("%s: unknown field(s): %s" % (where, sorted(extra)))

        date = cfg.get("date")
        if date is not None:
            if not isinstance(date, dict):
                errors.append("%s: 'date' must be a mapping" % where)
            elif set(date) - DATE_KEYS:
                errors.append("%s: invalid date key(s): %s" % (where, sorted(set(date) - DATE_KEYS)))
        link = cfg.get("link")
        if link is not None:
            if not isinstance(link, dict):
                errors.append("%s: 'link' must be a mapping" % where)
            elif set(link) - LINK_KEYS:
                errors.append("%s: invalid link key(s): %s" % (where, sorted(set(link) - LINK_KEYS)))

        mi = cfg.get("max_items")
        if mi is not None and (isinstance(mi, bool) or not isinstance(mi, int) or mi <= 0):
            errors.append("%s: max_items must be a positive integer" % where)

        rec = cfg.get("recipe")
        if rec and not os.path.exists(os.path.join("recipes", "%s.py" % rec)):
            errors.append("%s: recipe module recipes/%s.py not found" % (where, rec))

    # quality gate: build feeds added relative to the base
    if base_path and os.path.exists(base_path):
        base_ids = {c.get("id") for c in load(base_path) if isinstance(c, dict)}
        added = [c for c in feeds if isinstance(c, dict) and c.get("id")
                 and c["id"] not in base_ids and not c.get("disabled")]
        if not added:
            print("No newly added feeds to smoke-build.")
        for cfg in added:
            fid = cfg["id"]
            try:
                n = generate.build_feed(cfg)  # fetches via safe_get (SSRF-guarded)
                if n == 0:
                    errors.append("'%s': built 0 items — selectors don't match the page" % fid)
                elif n < 3:
                    warnings.append("'%s': only %d item(s) — selectors may be wrong" % (fid, n))
                else:
                    print("[ok] '%s' built %d items" % (fid, n))
            except generate.UnsafeURLError as e:
                errors.append("'%s': url not allowed: %s" % (fid, e))
            except Exception as e:
                errors.append("'%s': build failed: %s" % (fid, e))

    for w in warnings:
        print("::warning::%s" % w)
    for e in errors:
        print("::error::%s" % e)
    if errors:
        print("\nFAILED: %d error(s), %d warning(s)." % (len(errors), len(warnings)))
        sys.exit(1)
    print("\nOK: %d feed(s) valid, %d warning(s), no errors." % (len(feeds), len(warnings)))


if __name__ == "__main__":
    main()
