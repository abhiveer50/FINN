"""Quarterly-results extraction: filing PDF -> Revenue/EBITDA/PBT/PAT/EPS, QoQ & YoY.
Cheap text extraction locally; one small-model call for the table; derivations in code."""
import io, json, os, re, requests
import pandas as pd
from urllib.parse import quote

METRICS = ("revenue", "ebitda", "pbt", "pat", "eps")
MODEL = os.getenv("FINN_MODEL", "claude-haiku-5-5")
PROMPT = ("From this Indian listed-company quarterly results filing, return ONLY JSON: "
          '{"cur":{...},"prev_q":{...},"yoy_q":{...}} with keys revenue, ebitda, pbt, pat, eps '
          "(Rs crore except eps; consolidated if both exist; null if absent). cur=latest quarter, "
          "prev_q=preceding quarter, yoy_q=same quarter last year. EBITDA = PBT + finance cost + depreciation "
          "- other income if not stated.\n\n")

def _pct(a, b):
    return None if a is None or b is None or b <= 0 else round((a / b - 1) * 100, 1)

def _mg(d, k):
    return d[k] / d["revenue"] * 100 if d.get(k) is not None and d.get("revenue") else None

def derive(cur, prev, yoy):
    out = {k: {"val": cur.get(k), "qoq": _pct(cur.get(k), prev.get(k)), "yoy": _pct(cur.get(k), yoy.get(k))}
           for k in METRICS}
    mg = {}
    for k in ("ebitda", "pat"):
        c, p, y = _mg(cur, k), _mg(prev, k), _mg(yoy, k)
        mg[k] = None if c is None else round(c, 1)
        mg[k + "_qoq_bps"] = None if None in (c, p) else round((c - p) * 100)
        mg[k + "_yoy_bps"] = None if None in (c, y) else round((c - y) * 100)
    out["margins"] = mg
    return out

def _mv(p): return "n/a" if p is None else f"{'up' if p >= 0 else 'down'} {abs(p):.1f}%"
def _bp(b): return "n/a" if b is None else f"{'expanded' if b >= 0 else 'contracted'} {abs(b)} bps"

def narrate(r, per):
    """Deterministic summary from the numbers (no LLM -> no hallucinated figures)."""
    rev, eb, pat, eps, mg = r["revenue"], r["ebitda"], r["pat"], r["eps"], r["margins"]
    lbl = (r.get("meta") or {}).get("ebitda_label", "EBITDA")
    out = []
    if rev["val"] is not None:
        out.append(f"Revenue was ₹{rev['val']:,.0f} cr, {_mv(rev['yoy'])} YoY and {_mv(rev['qoq'])} QoQ.")
    if eb["val"] is not None and mg.get("ebitda") is not None:
        out.append(f"{lbl} of ₹{eb['val']:,.0f} cr gives a {mg['ebitda']}% margin, which {_bp(mg['ebitda_yoy_bps'])} YoY and {_bp(mg['ebitda_qoq_bps'])} QoQ.")
    if pat["val"] is not None:
        out.append(f"PAT came in at ₹{pat['val']:,.0f} cr ({_mv(pat['yoy'])} YoY, {_mv(pat['qoq'])} QoQ), a {mg.get('pat')}% net margin.")
    if eps["val"] is not None:
        out.append(f"EPS was ₹{eps['val']} ({_mv(eps['yoy'])} YoY).")
    return " ".join(out)

class Stale(Exception): pass
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
_ROWS = {"revenue": ("sales", "revenue"), "ebitda": ("operating profit", "financing profit"),
         "pbt": ("profit before tax",), "pat": ("net profit",), "eps": ("eps in rs",)}

def parse_screener_quarters(html, want=None):
    """screener.in quarterly table -> derive(). Columns are quarters, latest last."""
    m = re.search(r'<section id="quarters".*?</section>', html, re.S)
    if not m: raise RuntimeError("no quarterly table on screener.in page")
    df = pd.read_html(io.StringIO(m.group(0)))[0]
    df.index = [re.sub(r"[\s\u00a0+]+$", "", str(x)).lower() for x in df.iloc[:, 0]]
    df = df.iloc[:, 1:].apply(lambda c: pd.to_numeric(c.astype(str).str.replace(r"[,%]", "", regex=True), errors="coerce"))
    cols = [str(c) for c in df.columns]
    if len(cols) < 2: raise RuntimeError("too few quarters")
    if want and cols[-1] != want:
        raise Stale(f"screener.in has not posted {want} yet (latest: {cols[-1]})")
    def col(j):
        out = {}
        for k, prefixes in _ROWS.items():
            out[k] = None
            for n in df.index:
                if any(n.startswith(p) for p in prefixes):
                    v = df.loc[n].iloc[j]; out[k] = None if pd.isna(v) else float(v); break
        return out
    cur, prev = col(-1), col(-2)
    yoy = col(-5) if len(cols) >= 5 else {k: None for k in METRICS}
    out = derive(cur, prev, yoy)
    bank = any(n.startswith("financing profit") for n in df.index)
    out["meta"] = {"source": "screener.in", "as_of": cols[-1], "ebitda_label": "Financing profit" if bank else "EBITDA",
                   "margin_label": "Financing margin" if bank else "EBITDA margin"}
    return out

def from_screener(sym, want=None):
    last = None
    for path in (f"{quote(sym)}/consolidated/", f"{quote(sym)}/"):
        try:
            r = requests.get(f"https://www.screener.in/company/{path}", headers=UA, timeout=20)
            if r.ok: return parse_screener_quarters(r.text, want)
            last = f"HTTP {r.status_code}"
        except Stale: raise
        except Exception as e: last = str(e)[:80]
    raise RuntimeError(f"screener.in: {last}")

def extract(pdf_url):
    """Fallback: read numbers from the filing PDF with one small-model call."""
    import pdfplumber
    if not os.getenv("ANTHROPIC_API_KEY"): raise RuntimeError("ANTHROPIC_API_KEY not set")
    import anthropic
    s = requests.Session(); s.headers.update(UA)
    try: s.get("https://www.nseindia.com", timeout=10)          # cookie warm-up; NSE archives reject cold requests
    except Exception: pass
    resp = s.get(pdf_url, headers={"Referer": "https://www.nseindia.com/"}, timeout=30)
    if not resp.ok or not resp.content[:4] == b"%PDF": raise RuntimeError(f"PDF download blocked (HTTP {resp.status_code})")
    with pdfplumber.open(io.BytesIO(resp.content)) as p:
        text = "\n".join((pg.extract_text() or "") for pg in p.pages[:4])[:12000]
    if len(text.strip()) < 200: raise RuntimeError("PDF has no readable text (scanned?)")
    msg = anthropic.Anthropic().messages.create(model=MODEL, max_tokens=600,
          messages=[{"role": "user", "content": PROMPT + text}])
    j = json.loads(re.search(r"\{.*\}", msg.content[0].text, re.S).group(0))
    out = derive(j["cur"], j["prev_q"], j["yoy_q"])
    out["meta"] = {"source": "filing PDF", "as_of": None, "ebitda_label": "EBITDA", "margin_label": "EBITDA margin"}
    return out

def extract_any(a):
    """Screener table first (free, exact, covers banks); filing PDF + model as fallback.
    Returns (result_or_None, reason_if_none)."""
    why = []
    try: return from_screener(a["symbol"], a.get("period_end")), None
    except Exception as e: why.append(str(e))
    if a.get("pdf"):
        try: return extract(a["pdf"]), None
        except Exception as e: why.append("filing PDF: " + str(e)[:100])
    else: why.append("no filing PDF attached")
    return None, " · ".join(why)
