#!/usr/bin/env python3
"""
Config-driven RSS factory.

Reads feeds.yaml, builds one RSS 2.0 file per feed into docs/<id>.xml,
and writes docs/index.html listing every feed.

Each feed is described with CSS selectors (no code needed). For sites that
are too quirky for selectors, point `recipe:` at a module in recipes/.
"""
import os, re, html, sys, importlib, socket, ipaddress
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
CONFIG = os.path.join(HERE, "feeds.yaml")

# Where the feeds will be served from (used for the atom:self link).
# Edit this if you rename the repo or use a custom domain.
SITE_BASE_URL = "https://mjenkinsx9.github.io/rss-feeds"

UA = {"User-Agent": "rss-feeds (+https://github.com/mjenkinsx9/rss-feeds)"}
KEEP = {"a","ul","ol","li","p","code","pre","strong","em","b","i","br","h4","blockquote"}
DROP = {"script","style","svg","button","nav","form","input","img","path","iframe"}

# --- SSRF guard --------------------------------------------------------------
# Feed URLs can come from untrusted sources (e.g. the feed-request bot fetches a
# URL submitted in a public issue, from inside CI). Block requests that resolve
# to non-public addresses (loopback, private, link-local, cloud metadata, etc.),
# restrict to http/https on ports 80/443, and follow redirects manually so each
# hop is re-validated. Residual risk: DNS rebinding between resolve and connect
# (a known limitation of resolve-then-request without IP pinning) — acceptable
# here because the bot's output is a human-reviewed PR, not an auto-publish.
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
_BLOCKED_NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "::1/128", "::/128", "fc00::/7", "fe80::/10",
)]


class UnsafeURLError(Exception):
    """Raised when a URL is disallowed by the SSRF guard."""


def _addr_blocked(ip_str):
    ip = ipaddress.ip_address(ip_str)
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified):
        return True
    return any(ip in net for net in _BLOCKED_NETS)


def assert_public_url(url):
    """Validate scheme/port/credentials and that the host resolves to a public IP."""
    p = urlparse(url)
    if p.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError("only http and https URLs are allowed")
    if p.username or p.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")
    host = (p.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("missing host")
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UnsafeURLError("only ports 80 and 443 are allowed")
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError("could not resolve host: %s" % e)
    addrs = {info[4][0] for info in infos}
    if not addrs:
        raise UnsafeURLError("host did not resolve")
    for a in addrs:
        if _addr_blocked(a):
            raise UnsafeURLError("host resolves to a non-public address (%s)" % a)
    return host


def safe_get(url, headers=None, timeout=40, max_redirects=5):
    """requests.get with an SSRF guard and manual, re-validated redirects."""
    for _ in range(max_redirects + 1):
        assert_public_url(url)
        r = requests.get(url, headers=headers or {}, timeout=timeout, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = urljoin(url, r.headers["Location"])
            continue
        return r
    raise UnsafeURLError("too many redirects")


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-") or "item"


def abs_url(href, base):
    if not href:
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        m = re.match(r"(https?://[^/]+)", base)
        return (m.group(1) if m else "") + href
    if href.startswith("http"):
        return href
    return base.rstrip("/") + "/" + href.lstrip("/")


def clean_body(el, base):
    """Turn an element's HTML into a small, safe HTML string for the feed."""
    if el is None:
        return ""
    soup = BeautifulSoup(str(el), "html.parser")
    for tag in soup.find_all(list(DROP)):
        tag.decompose()
    for tag in soup.find_all(["h1","h2","h3"]):
        tag.name = "h4"
    for tag in soup.find_all(True):
        if tag.name not in KEEP:
            tag.unwrap()
        else:
            attrs = {}
            if tag.name == "a" and tag.get("href"):
                attrs["href"] = abs_url(tag["href"], base)
            tag.attrs = attrs
    out = re.sub(r"\n{3,}", "\n\n", str(soup)).strip()
    return out


def parse_date(text, fmt=None):
    text = (text or "").strip()
    if not text:
        return None
    try:
        if fmt:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        return dateparser.parse(text).replace(tzinfo=timezone.utc) if dateparser.parse(text).tzinfo is None else dateparser.parse(text)
    except Exception:
        return None


def extract_date(item, dcfg):
    if not dcfg:
        return None
    fmt = dcfg.get("format")
    # regex over the item's text
    if dcfg.get("regex"):
        m = re.search(dcfg["regex"], item.get_text(" ", strip=True))
        return parse_date(m.group(0), fmt) if m else None
    # selector -> attribute or text
    sel = dcfg.get("selector")
    node = item.select_one(sel) if sel else item
    if node is None:
        return None
    if dcfg.get("attr"):
        return parse_date(node.get(dcfg["attr"], ""), fmt)
    return parse_date(node.get_text(" ", strip=True), fmt)


def extract_link(item, lcfg, page_url, title):
    lcfg = lcfg or {}
    if lcfg.get("base_anchor"):
        return "%s#%s" % (page_url, slug(title))
    sel = lcfg.get("selector")
    node = item.select_one(sel) if sel else item.find("a")
    if node is not None:
        href = node.get(lcfg.get("attr", "href"))
        if href:
            return abs_url(href, page_url)
    return page_url


def extract_text(item, sel):
    if not sel:
        return None
    node = item.select_one(sel)
    if node is None:
        return None
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def parse_with_selectors(html_text, cfg):
    soup = BeautifulSoup(html_text, "html.parser")
    items, seen = [], set()
    for el in soup.select(cfg["item"]):
        title = extract_text(el, cfg.get("entry_title")) or \
                (el.get_text(" ", strip=True)[:80] if not cfg.get("entry_title") else None)
        if not title:
            continue
        dt = extract_date(el, cfg.get("date"))
        link = extract_link(el, cfg.get("link"), cfg["url"], title)
        body_el = el.select_one(cfg["body"]) if cfg.get("body") else None
        body = clean_body(body_el if body_el is not None else el, cfg["url"])
        key = (title, dt.isoformat() if dt else "")
        if key in seen:
            continue
        seen.add(key)
        items.append({"title": title, "date": dt, "link": link, "html": body})
    return items


def build_feed(cfg):
    fid = cfg["id"]
    url = cfg["url"]
    r = safe_get(url, headers=UA, timeout=40)
    r.raise_for_status()

    if cfg.get("recipe"):
        mod = importlib.import_module("recipes." + cfg["recipe"])
        items = mod.parse(r.text, cfg)
    else:
        items = parse_with_selectors(r.text, cfg)

    # sort newest first when dates exist; else keep document order
    if items and all(i["date"] for i in items):
        items.sort(key=lambda i: i["date"], reverse=True)
    if cfg.get("max_items"):
        items = items[: int(cfg["max_items"])]

    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    self_url = "%s/%s.xml" % (SITE_BASE_URL, fid)
    desc = cfg.get("description") or ("Unofficial RSS feed for %s" % url)

    parts = []
    for it in items:
        pub = ""
        if it["date"]:
            pub = "      <pubDate>%s</pubDate>\n" % it["date"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        guid = "%s-%s-%s" % (fid, (it["date"].strftime("%Y%m%d") if it["date"] else "x"), slug(it["title"]))
        parts.append(
"    <item>\n"
"      <title>%s</title>\n"
"      <link>%s</link>\n"
"      <guid isPermaLink=\"false\">%s</guid>\n"
"%s"
"      <description><![CDATA[%s]]></description>\n"
"    </item>" % (html.escape(it["title"]), html.escape(it["link"]), html.escape(guid), pub, it["html"]))

    feed = (
'<?xml version="1.0" encoding="UTF-8"?>\n'
'<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
"  <channel>\n"
"    <title>%s</title>\n"
"    <link>%s</link>\n"
'    <atom:link href="%s" rel="self" type="application/rss+xml"/>\n'
"    <description>%s</description>\n"
"    <language>en-us</language>\n"
"    <lastBuildDate>%s</lastBuildDate>\n"
"    <generator>rss-feeds</generator>\n"
"%s\n"
"  </channel>\n"
"</rss>\n" % (html.escape(cfg["title"]), html.escape(url), html.escape(self_url),
              html.escape(desc), now, "\n".join(parts)))

    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, fid + ".xml"), "w", encoding="utf-8") as f:
        f.write(feed)
    return len(items)


def write_index(feeds, results):
    rows = []
    for cfg in feeds:
        fid = cfg["id"]
        n = results.get(fid, "error")
        rows.append(
            '<li><a class="feed" href="./%s.xml">%s</a>'
            '<span class="meta">%s items &middot; '
            '<a href="%s">source</a></span></li>'
            % (fid, html.escape(cfg["title"]), n, html.escape(cfg["url"])))
    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RSS feeds</title>
<style>
 body{{font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:44rem;margin:3rem auto;padding:0 1.25rem;color:#111;background:#fafafa}}
 h1{{margin-bottom:.25rem}} p.sub{{color:#666;margin-top:0}}
 ul{{list-style:none;padding:0}} li{{padding:.9rem 0;border-bottom:1px solid #e5e5e5}}
 a.feed{{font-weight:600;font-size:1.05rem;text-decoration:none;color:#0b65c2}}
 .meta{{display:block;color:#777;font-size:.85rem;margin-top:.15rem}}
 a{{color:#0b65c2}} footer{{margin-top:2rem;color:#888;font-size:.85rem}}
</style></head><body>
<h1>RSS feeds</h1>
<p class="sub">Auto-generated feeds, rebuilt every few hours. Paste any feed URL into your reader.</p>
<ul>
{rows}
</ul>
<footer>Unofficial reformatting of public pages into RSS. Source content belongs to the respective sites.</footer>
</body></html>
""".format(rows="\n".join(rows))
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)


def main():
    with open(CONFIG, encoding="utf-8") as f:
        feeds = [c for c in yaml.safe_load(f) if c and not c.get("disabled")]
    results, failed = {}, 0
    for cfg in feeds:
        try:
            n = build_feed(cfg)
            results[cfg["id"]] = n
            print("[ok]  %-20s %3d items" % (cfg["id"], n))
        except Exception as e:
            failed += 1
            print("[ERR] %-20s %s" % (cfg.get("id","?"), e), file=sys.stderr)
    write_index(feeds, results)
    print("Done. %d feed(s), %d failed." % (len(feeds), failed))
    # don't fail the whole CI run for one broken site, but do surface it
    sys.exit(0)


if __name__ == "__main__":
    main()
