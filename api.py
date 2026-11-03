import os, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from prices import WINDOWS, load_prices, stock_returns, ew_performance, movers
from announcements import (fetch_all, cached, prep, headline, screener_url, one_liner, CATS)
import demo_data, results as res
from config import PORTFOLIO

DEMO = os.getenv("FINN_DEMO") == "1"
app = FastAPI(title="FINN")
POOL = ThreadPoolExecutor(4)

def get_prices():
    if DEMO: return demo_data.prices(), "sample"
    try: return load_prices(), "live"
    except Exception as e:
        print("prices fallback:", e); return demo_data.prices(), "sample"

def get_ann(days=7):
    if DEMO: return prep(demo_data.announcements()), "sample"
    try: return prep(fetch_all(days)), "live"
    except Exception as e:
        print("announcements fallback:", e); return prep(demo_data.announcements()), "sample"

_RC = {}
def get_results(a, src):
    """-> (results|None, reason). Successes cached 24h, failures only 5 min so a fix/retry shows up fast."""
    if not a["is_results"]: return None, None
    hit = _RC.get(a["id"])
    if hit and (hit[0] or time.time() - hit[2] < 300): return hit[0], hit[1]
    if src == "sample":
        r = demo_data.results(a["symbol"]); why = None if r else "no sample numbers for this company"
    else:
        r, why = res.extract_any(a)
    _RC[a["id"]] = (r, why, time.time())
    return r, why

# ---------------- push: portfolio
@app.get("/api/summary")
def summary(window: str = "1D"):
    lb = WINDOWS[window]
    close, src = cached("px", 900, get_prices)
    r, short = stock_returns(close, lb)
    perf, curve = ew_performance(close, lb)
    up, dn = movers(r)
    sec = lambda d: [{"symbol": k, "pct": round(v, 2), "sector": PORTFOLIO.get(k)} for k, v in d.items()]
    return {"window": window, "source": src, "ew_return": round(perf, 2),
            "curve": [round(x, 2) for x in curve.tolist()], "gainers": sec(up), "losers": sec(dn),
            "new_listings": short[short].index.tolist(), "n": int(r.notna().sum())}

# ---------------- push: announcements
@app.get("/api/announcements")
def announcements(days: int = 7, offset: int = 0, limit: int = 7, q: str = "", cat: str = ""):
    items, src = cached(f"ann{days}", 600, lambda: get_ann(days))
    ql = q.strip().lower()
    if ql:
        items = [a for a in items if ql in f'{a["symbol"]} {a["type"]} {a["text"]} {a["label"]} {a["cat"]}'.lower()]
    counts = Counter(a["cat"] for a in items)
    sel = [c for c in cat.split(",") if c]
    if sel: items = [a for a in items if a["cat"] in sel]
    page = [dict(a) for a in items[offset:offset + limit]]
    rs = list(POOL.map(lambda a: get_results(a, src)[0] if a["is_results"] else None, page))
    for a, r in zip(page, rs):
        a["headline"] = headline(a, r)
        a["sector"] = PORTFOLIO.get(a["symbol"])
    nxt = offset + limit if offset + limit < len(items) else None
    return {"items": page, "next": nxt, "total": len(items), "source": src,
            "categories": [{"name": c, "count": counts.get(c, 0)} for c in CATS]}

def _fundamentals(sym, src):
    if src == "sample": return demo_data.fundamentals(sym)
    def run():
        try:
            import yfinance as yf
            i = yf.Ticker(f"{sym}.NS").info
            g = lambda k: i.get(k)
            return {"pe": g("trailingPE"), "pb": g("priceToBook"),
                    "roe": None if g("returnOnEquity") is None else round(g("returnOnEquity") * 100, 1),
                    "de": None if g("debtToEquity") is None else round(g("debtToEquity") / 100, 2),
                    "mcap": None if g("marketCap") is None else round(g("marketCap") / 1e7),   # Rs crore
                    "target": g("targetMeanPrice"), "rating": g("recommendationKey"),
                    "n": g("numberOfAnalystOpinions"), "price": g("currentPrice")}
        except Exception: return {}
    return cached("f" + sym, 21600, run) or {}

def _price_card(sym):
    close, _ = cached("px", 900, get_prices)
    if sym not in close: return None
    s = close[sym].dropna()
    if len(s) < 2: return None
    pc = lambda n: round((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100, 2) if len(s) > n else None
    return {"last": round(float(s.iloc[-1]), 2), "d1": pc(1), "w1": pc(5), "curve": [round(float(x), 2) for x in s.tail(30)]}

@app.get("/api/announcements/{aid}")
def detail(aid: str):
    items, src = cached("ann7", 600, lambda: get_ann(7))
    a = next((dict(x) for x in items if x["id"] == aid), None)
    if not a: raise HTTPException(404)
    r, why = get_results(a, src)
    a["headline"] = headline(a, r)
    a["sector"] = PORTFOLIO.get(a["symbol"])
    a["price"] = _price_card(a["symbol"])
    a["related"] = [{"id": x["id"], "label": x["label"], "prio": x["prio"], "ts": x["ts"], "line": one_liner(x)}
                    for x in items if x["symbol"] == a["symbol"] and x["id"] != aid][:4]
    if a["is_results"]:
        f = _fundamentals(a["symbol"], src)
        a["screener"] = screener_url(a["symbol"], a["label"] == "Annual Results")
        a["results"] = r
        a["results_note"] = None if r else why
        a["narrative"] = res.narrate(r, a.get("period")) if r else None
        a["ratios"] = {k: f.get(k) for k in ("pe", "pb", "roe", "de", "mcap")}
        tp, px = f.get("target"), (a["price"] or {}).get("last") or f.get("price")
        a["analyst"] = ({"rating": f.get("rating"), "target": tp, "n": f.get("n"),
                         "upside": round((tp / px - 1) * 100, 1) if tp and px else None}
                        if f.get("rating") or tp or src == "sample" else None)
        if src == "sample" and a["analyst"]: a["analyst"].update(rating="buy", target=None, n=None)
    return a

app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/")
def index(): return FileResponse("static/index.html")
