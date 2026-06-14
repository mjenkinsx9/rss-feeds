#!/usr/bin/env python3
"""
Benchmark Claude models for the feed-request bot to find the cheapest effective one.

Runs the *exact* production system prompt + output schema (imported from
process_feed_request.py) against a set of graded cases — moderation (must reject)
and selector derivation (must approve AND produce working selectors) — across
several models, and reports accuracy, latency, tokens, and computed $ cost.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python .github/scripts/benchmark_models.py

No secrets are written anywhere; results print to stdout.
"""
import importlib.util
import json
import os
import sys
import time

import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # repo root
import generate  # noqa: E402

# import the production module (sibling file) to reuse its prompt + schema
_spec = importlib.util.spec_from_file_location("proc", os.path.join(HERE, "process_feed_request.py"))
proc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(proc)

# model id -> (input $/MTok, output $/MTok, thinking param or None)
MODELS = {
    "claude-haiku-4-5":  (1.0,  5.0,  None),                    # effort/adaptive unsupported
    "claude-sonnet-4-6": (3.0, 15.0,  {"type": "adaptive"}),
    "claude-opus-4-8":   (5.0, 25.0,  {"type": "adaptive"}),
}

APPROVE_BLOG = """<!doctype html><html><body><main>
<article class="post"><h2><a href="/p/alpha">Alpha release</a></h2>
  <time datetime="2026-01-05">Jan 5, 2026</time><div class="summary">First post body text.</div></article>
<article class="post"><h2><a href="/p/beta">Beta update</a></h2>
  <time datetime="2026-02-10">Feb 10, 2026</time><div class="summary">Second post body text.</div></article>
<article class="post"><h2><a href="/p/gamma">Gamma notes</a></h2>
  <time datetime="2026-03-15">Mar 15, 2026</time><div class="summary">Third post body text.</div></article>
<article class="post"><h2><a href="/p/delta">Delta changes</a></h2>
  <time datetime="2026-04-20">Apr 20, 2026</time><div class="summary">Fourth post body text.</div></article>
</main></body></html>"""

REJECT_GAMBLING = """<!doctype html><html><head><title>LuckySpin Casino — Bet & Win</title></head><body>
<h1>LuckySpin Online Casino</h1><p>Deposit now and claim your free bet. Slots, roulette, blackjack,
sports betting and the biggest jackpot odds online. Gamble responsibly. Place your bets!</p>
<ul><li>Latest jackpot winners</li><li>New slot machines</li><li>Live betting odds</li></ul></body></html>"""

REJECT_ADULT = """<!doctype html><html><head><title>XXX Adult Tube — Explicit Porn Videos</title></head><body>
<h1>Adults only — 18+ explicit pornographic content</h1>
<p>Thousands of XXX adult videos. Sexual explicit content for adults only.</p>
<div class="vid">Explicit video 1</div><div class="vid">Explicit video 2</div></body></html>"""

# kind: "approve_live" (fetch URL, expect approve + >=min_items) | "approve_html"
# (use html, expect approve + >=min_items) | "reject" (expect reject)
CASES = [
    {"name": "codex changelog (real)", "kind": "approve_live",
     "url": "https://developers.openai.com/codex/changelog", "min_items": 10},
    {"name": "generic blog (fixture)", "kind": "approve_html",
     "url": "https://blog.example.com/news", "html": APPROVE_BLOG, "min_items": 3},
    {"name": "gambling site (fixture)", "kind": "reject",
     "url": "https://casino.example.com/", "html": REJECT_GAMBLING},
    {"name": "adult site (fixture)", "kind": "reject",
     "url": "https://adult.example.com/", "html": REJECT_ADULT},
]


def user_content(url, html, req_title):
    return (
        "Review this feed request.\n\n<request>\n"
        f"requested_title: {req_title}\nrequested_id: (none — you choose)\nurl: {url}\n"
        "what_to_capture: (not specified)\nselector_hints: (none)\n</request>\n\n"
        f"If you approve, derive the selectors from the HTML below.\n\n"
        f'<page_html url="{url}">\n{html[:proc.HTML_LIMIT]}\n</page_html>'
    )


def run_case(client, model, thinking, case):
    if case["kind"] == "approve_live":
        html = generate.safe_get(case["url"], headers=proc.UA, timeout=40).text
    else:
        html = case["html"]

    kwargs = dict(
        model=model, max_tokens=8000, system=proc.SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": proc.RESULT_SCHEMA}},
        messages=[{"role": "user", "content": user_content(case["url"], html, case["name"])}],
    )
    if thinking:
        kwargs["thinking"] = thinking

    t0 = time.monotonic()
    msg = client.messages.create(**kwargs)
    dt = time.monotonic() - t0
    usage = msg.usage
    in_tok = usage.input_tokens + getattr(usage, "cache_read_input_tokens", 0) + getattr(usage, "cache_creation_input_tokens", 0)
    out_tok = usage.output_tokens

    if msg.stop_reason == "refusal":
        decision, ok, detail = "refusal", (case["kind"] == "reject"), "model refused"
    else:
        result = json.loads(next(b.text for b in msg.content if b.type == "text"))
        decision = result["decision"]
        if case["kind"] == "reject":
            ok = decision == "reject"
            detail = f'category={result.get("reject_category")}'
        else:
            ok = False
            detail = ""
            if decision == "approve" and result["feed"].get("item"):
                cfg = proc.build_cfg(result["feed"], case["url"])
                try:
                    n = len(generate.parse_with_selectors(html, cfg))
                except Exception as e:
                    n = -1
                    detail = f"parse error: {e}"
                ok = n >= case["min_items"]
                detail = detail or f'item="{cfg["item"]}" -> {n} items (need >={case["min_items"]})'
            else:
                detail = f"decision={decision} (expected approve)"
    return {"ok": ok, "decision": decision, "detail": detail, "dt": dt, "in": in_tok, "out": out_tok}


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY first, e.g.\n  "
                 "ANTHROPIC_API_KEY=sk-ant-... python .github/scripts/benchmark_models.py")
    client = anthropic.Anthropic()
    summary = []
    for model, (in_price, out_price, thinking) in MODELS.items():
        print(f"\n=== {model} ===")
        passed, cost, total_dt = 0, 0.0, 0.0
        for case in CASES:
            try:
                r = run_case(client, model, thinking, case)
            except Exception as e:
                print(f"  [ERR ] {case['name']:26} {e}")
                continue
            c = r["in"] / 1e6 * in_price + r["out"] / 1e6 * out_price
            cost += c
            total_dt += r["dt"]
            passed += 1 if r["ok"] else 0
            mark = "PASS" if r["ok"] else "FAIL"
            print(f"  [{mark}] {case['name']:26} {r['dt']:5.1f}s  "
                  f"{r['in']:>6}in/{r['out']:>5}out  ${c:.4f}  {r['detail']}")
        summary.append((model, passed, len(CASES), cost, total_dt))

    print("\n================ SUMMARY ================")
    print(f"{'model':20} {'score':>7} {'cost/run':>10} {'avg lat':>9}")
    for model, passed, total, cost, total_dt in summary:
        print(f"{model:20} {passed}/{total:<5} ${cost:>8.4f} {total_dt/len(CASES):>7.1f}s")
    print("\nCost is for ALL cases in one run; per real issue it's ~1 call.")
    cheapest_ok = [s for s in summary if s[1] == s[2]]
    if cheapest_ok:
        best = min(cheapest_ok, key=lambda s: s[3])
        print(f"\nCheapest model passing every case: {best[0]} (${best[3]:.4f}/run)")
    else:
        print("\nNo model passed every case — review the FAIL rows above.")


if __name__ == "__main__":
    main()
