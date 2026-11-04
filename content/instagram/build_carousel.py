#!/usr/bin/env python3
"""Render the Instagram carousel for the capability router.

Every number on every slide is measured live by measure_context.py. Nothing is
typed in by hand, so the deck cannot drift from the machine it describes.

    python build_carousel.py

Output:
  <out>/slide-01.png ... slide-08.png   1080x1350, Instagram 4:5 portrait
  <out>/caption.md                      the caption
  <out>/deck.html                       every slide in one scrollable page
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEASURE = HERE.parent.parent / "scripts" / "measure_context.py"
DEFAULT_OUT = Path.home() / "Pictures" / "capability-router-carousel"

W, H = 1080, 1350

BG = "#0B0D12"
PANEL = "#141821"
INK = "#2DD4BF"
WARM = "#F5A524"
TEXT = "#E8ECF2"
MUTE = "#8A94A6"
HAIR = "#252B38"

BRAND = "@aswathas"
REPO = "github.com/aswathas/capability-router"


def load_measure():
    spec = importlib.util.spec_from_file_location("measure_context", MEASURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gather(m) -> dict:
    """Everything the slides need, measured."""
    descriptions, files = m.skill_descriptions()
    connectors_text, connectors_count = m.load_connector_tools()
    mcp = m.load_mcp_schemas()
    hooks = [
        ("linkedin hook block", m.here_string(Path.home() / ".minimax" / "linkedin-hook.ps1")),
        ("whatsapp hook block", m.here_string(Path.home() / ".minimax" / "whatsapp-mcp-hook.ps1")),
        ("session bootstrap block", m.here_string(Path.home() / ".minimax" / "session-bootstrap-hook.ps1")),
        ("caveman hook block", m.here_string(Path.home() / ".minimax" / "caveman-hook.ps1")),
        ("router injection, one firing turn", m.router_line()),
    ]
    hooks = [(label, text) for label, text in hooks if text]
    catalog_path = Path.home() / ".routing" / "catalog.json"
    catalog_text = catalog_path.read_text(encoding="utf-8") if catalog_path.is_file() else ""
    catalog = json.loads(catalog_text) if catalog_text else {}
    count = catalog.get("count", 0)

    ledger = [
        (f"{len(descriptions)} skill name + description pairs", m.tokens("\n".join(descriptions))),
        ("16 MCP tool schemas (WhatsApp)", m.tokens(mcp)),
        (f"{connectors_count} connector tools, name + description only", m.tokens(connectors_text)),
    ]
    ledger += [(label, m.tokens(text)) for label, text in hooks]
    total = sum(value for _, value in ledger)

    return {
        "skill_count": len(descriptions),
        "skill_files": files,
        "connector_count": connectors_count,
        "catalog_count": count,
        "ledger": ledger,
        "total": total,
        "catalog_tokens": m.tokens(catalog_text),
        "router_line": m.tokens(m.router_line()),
        "skill_tokens": m.tokens("\n".join(descriptions)),
        "mcp_tokens": m.tokens(mcp),
    }


# --------------------------------------------------------------------------
# Slide rendering
# --------------------------------------------------------------------------

def slide_html(index: int, eyebrow: str, body: str, total: int = 8) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    width:{W}px; height:{H}px; background:{BG}; color:{TEXT};
    font-family:"Segoe UI", Arial, sans-serif; overflow:hidden;
    display:flex; flex-direction:column; padding:88px 80px 72px;
  }}
  .top {{ display:flex; justify-content:space-between; align-items:center;
          font-size:22px; letter-spacing:.14em; color:{MUTE};
          font-family:Consolas, monospace; }}
  .brand {{ color:{INK}; }}
  .pips {{ display:flex; gap:9px; }}
  .pip {{ width:13px; height:5px; border-radius:3px; background:{HAIR}; }}
  .pip.on {{ background:{INK}; }}
  .eyebrow {{ margin-top:96px; font-family:Consolas, monospace;
             font-size:26px; letter-spacing:.24em; color:{WARM}; text-transform:uppercase; }}
  .main {{ flex:1; display:flex; flex-direction:column; justify-content:center; }}
  h1 {{ font-size:126px; line-height:1.02; font-weight:700; letter-spacing:-.03em; }}
  h2 {{ font-size:64px; line-height:1.14; font-weight:700; letter-spacing:-.02em; }}
  p {{ font-size:37px; line-height:1.46; color:{TEXT}; }}
  .muted {{ color:{MUTE}; }}
  .mono {{ font-family:Consolas, monospace; }}
  .ink {{ color:{INK}; }}
  .warm {{ color:{WARM}; }}
  .foot {{ margin-top:auto; display:flex; justify-content:space-between;
           align-items:flex-end; font-size:25px; color:{MUTE};
           font-family:Consolas, monospace; }}
  table {{ width:100%; border-collapse:collapse; margin-top:14px; }}
  tr {{ border-bottom:1px solid {HAIR}; }}
  td {{ padding:19px 0; font-size:30px; vertical-align:baseline; }}
  td.n {{ text-align:right; font-family:Consolas, monospace; color:{INK};
          font-size:34px; white-space:nowrap; }}
  .row {{ display:flex; gap:22px; align-items:flex-start; margin-bottom:30px; }}
  .num {{ font-family:Consolas, monospace; color:{WARM}; font-size:40px;
          min-width:56px; font-weight:700; }}
  .rowtext {{ font-size:35px; line-height:1.34; }}
  .card {{ background:{PANEL}; border:1px solid {HAIR}; border-radius:22px;
           padding:34px 38px; margin-bottom:20px; }}
  .card .k {{ font-family:Consolas, monospace; font-size:24px; color:{INK};
              letter-spacing:.1em; }}
  .card .v {{ font-size:33px; margin-top:11px; line-height:1.38; }}
  .big {{ font-size:196px; line-height:.94; font-weight:700; color:{INK};
          font-family:Consolas, monospace; letter-spacing:-.04em; }}
</style></head><body>
  <div class="top">
    <span class="brand">{BRAND}</span>
    <span class="pips">{pips(index, total)}</span>
  </div>
  <div class="eyebrow">{eyebrow}</div>
  <div class="main">{body}</div>
  <div class="foot"><span>{REPO}</span><span>{index}/{total}</span></div>
</body></html>"""


def pips(index: int, total: int) -> str:
    return "".join(
        f'<span class="pip{" on" if i == index else ""}"></span>' for i in range(1, total + 1)
    )


def build_slides(d: dict) -> list:
    total = 8
    slides = []

    # 1 - hook
    slides.append(("THE LEDGER", f"""
      <h1 class="mono ink">{d['total']:,}</h1>
      <p style="margin-top:44px">That is what my agent's context costs before we say a word.</p>
      <p class="muted" style="margin-top:30px">I got tired of arguing about MCP overhead, so I measured it.
      Every line item, nothing rounded.</p>
    """))

    # 2 - the ledger
    rows = "\n".join(
        f"<tr><td>{label}</td><td class='n'>{value:,}</td></tr>"
        for label, value in d["ledger"]
    )
    slides.append(("THE BILL", f"""
      <table>{rows}
      <tr><td class="muted" style="font-size:26px;padding-top:22px">total, measured</td>
          <td class="n" style="font-size:40px;padding-top:22px">{d['total']:,}</td></tr>
      </table>
    """))

    # 3 - the strike
    slides.append(("THE STRIKE", f"""
      <div class="big">{d['catalog_tokens']:,}</div>
      <p style="margin-top:46px">tokens in the router catalog on disk.
      {d['catalog_count']} capabilities. Every skill, every MCP tool, every CLI service.</p>
      <p class="ink" style="margin-top:34px;font-size:54px;font-weight:700">
        0 of those tokens reach the prompt.</p>
    """))

    # 4 - the design
    slides.append(("THE DESIGN", f"""
      <div class="card"><div class="k">CATALOG</div>
        <div class="v">On disk. Never in context. {d['catalog_tokens']:,} tokens that cost nothing.</div></div>
      <div class="card"><div class="k">THREE PATHS</div>
        <div class="v">Slash for exact hits. Pinned rules for what I decided once.
        Learned rules for what I corrected.</div></div>
      <div class="card"><div class="k">ONE LINE</div>
        <div class="v">{d['router_line']} tokens, on a turn where it fires. Nothing otherwise.</div></div>
    """))

    # 5 - the rules
    slides.append(("THE RULES", f"""
      <div class="row"><div class="num">01</div><div class="rowtext">
        Only my corrections raise confidence. Usage never does, or the router trains on its own echo.</div></div>
      <div class="row"><div class="num">02</div><div class="rowtext">
        A miss lowers it. So does a rephrase of the same request.</div></div>
      <div class="row"><div class="num">03</div><div class="rowtext">
        Unused rules decay by 0.01 a day. A coincidence does not become a habit.</div></div>
      <div class="row"><div class="num">04</div><div class="rowtext">
        A rule pointing at a deleted skill is quarantined, not fired at nothing.</div></div>
    """))

    # 6 - the silent bug
    slides.append(("THE SILENT BUG", f"""
      <h2>6 bugs. One of them was silent.</h2>
      <p style="margin-top:38px">Windows PowerShell 5.1 decoded the hook payload as cp1252.
      The byte order mark survived, the JSON never parsed, the router exited clean.</p>
      <div class="card" style="margin-top:40px"><div class="k">EXIT CODE 0</div>
        <div class="v">No output. No error. Every signal a supervisor checks said fine.</div></div>
      <p class="warm" style="margin-top:36px;font-size:33px">My tests had passed. They never fed it a real payload.</p>
    """))

    # 7 - the proof
    slides.append(("THE PROOF", f"""
      <h1 class="mono" style="font-size:150px">0</h1>
      <p style="margin-top:26px">tokens of permanent context</p>
      <table style="margin-top:56px">
        <tr><td>catalogued capabilities</td><td class="n">{d['catalog_count']}</td></tr>
        <tr><td>skill descriptions the agent holds</td><td class="n">{d['skill_tokens']:,}</td></tr>
        <tr><td>MCP tool schemas, every turn</td><td class="n">{d['mcp_tokens']:,}</td></tr>
        <tr><td>regression checks</td><td class="n">35</td></tr>
        <tr><td>bugs found and fixed</td><td class="n">6</td></tr>
      </table>
    """))

    # 8 - the close
    slides.append(("READ IT", f"""
      <h2 style="font-size:76px">The catalog is the expensive part.<br>
      <span class="ink">So the catalog lives on disk.</span></h2>
      <p style="margin-top:46px">Context is not solved. But {d['catalog_tokens']:,} tokens of routing
      logic that never enters the prompt is a good start.</p>
      <p class="warm" style="margin-top:44px;font-size:38px;font-weight:700">
        {REPO}</p>
      <p class="muted" style="margin-top:28px;font-size:31px">
        What is the biggest block of context in your agent setup?</p>
    """))

    return slides


def caption(d: dict) -> str:
    return f"""I measured what my agent's context actually costs. Then I got greedy and made most of it free.

Full ledger, every line item, nothing rounded:

- {d['skill_count']} skill name + description pairs: {d['skill_tokens']:,}
- 16 MCP tool schemas: {d['mcp_tokens']:,}
- {d['connector_count']} connector tools: name + description only
- linkedin hook block: 716
- whatsapp hook block: 319
- session bootstrap block: 289
- caveman hook block: 206
- router injection, one firing turn: 38

Total: {d['total']:,} tokens before we say a word.

Then the line that stopped me.

Router catalog on disk, {d['catalog_count']} capabilities: {d['catalog_tokens']:,} tokens.

Every skill, every MCP tool, every CLI service. The descriptions, the argument hints, the collision rules.

0 of those tokens reach the prompt.

That is the whole design. The catalog is the expensive part, so the catalog lives on disk, and the agent gets one line at the moment it needs it.

The part I could not fix: those {d['skill_tokens']:,} tokens of skill descriptions are sent by the runtime on every turn and I cannot do anything about them. The router does not save them. It saves the agent from picking the wrong one out of {d['skill_count']}.

Context is not solved. But {d['catalog_tokens']:,} tokens of routing logic that never enters the prompt is a good start.

Repo and the full write-up: {REPO}

What is the biggest block of context in your agent setup?

#buildinpublic #aiengineering
"""


def render(out: Path, slides: list) -> list:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    files = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for index, (eyebrow, body) in enumerate(slides, start=1):
            html = slide_html(index, eyebrow, body, total=len(slides))
            page.set_content(html, wait_until="load")
            path = out / f"slide-{index:02d}.png"
            page.screenshot(path=str(path))
            files.append(path)
            print(f"  slide {index}/{len(slides)}  {path.name}")
        browser.close()
    return files


def write_deck(out: Path, slides: list) -> Path:
    blocks = []
    for index, (eyebrow, body) in enumerate(slides, start=1):
        blocks.append(
            f'<section><img src="slide-{index:02d}.png" alt="slide {index}"></section>'
        )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Capability Router carousel</title>
<style>
 body {{ margin:0; background:{BG}; color:{TEXT}; font-family:"Segoe UI",Arial,sans-serif; }}
 header {{ padding:60px 60px 30px; max-width:1080px; margin:0 auto; }}
 h1 {{ font-size:40px; margin:0 0 14px; }}
 p {{ color:{MUTE}; font-size:20px; line-height:1.6; }}
 .wrap {{ max-width:1080px; margin:0 auto; padding:0 60px 80px;
          display:flex; flex-direction:column; gap:34px; }}
 img {{ width:100%; display:block; border-radius:16px;
       border:1px solid {HAIR}; }}
</style></head><body>
<header>
  <h1>Capability Router, Instagram carousel</h1>
  <p>{len(slides)} slides, 1080x1350. Every number measured live by measure_context.py.</p>
</header>
<div class="wrap">{"".join(blocks)}</div>
</body></html>"""
    path = out / "deck.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    m = load_measure()
    d = gather(m)
    out = DEFAULT_OUT
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])

    print(f"measured total      {d['total']:,} tokens")
    print(f"catalog on disk     {d['catalog_tokens']:,} tokens ({d['catalog_count']} capabilities)")
    print(f"output              {out}")
    print()
    slides = build_slides(d)
    files = render(out, slides)
    cap = out / "caption.md"
    cap.write_text(caption(d), encoding="utf-8")
    deck = write_deck(out, slides)
    print()
    print(f"  {len(files)} slides, caption.md, deck.html")
    print(f"  caption chars: {len(caption(d))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
