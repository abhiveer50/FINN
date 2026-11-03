import hashlib, re, time, os, requests, datetime as dt
from config import PORTFOLIO

NSE = "https://www.nseindia.com"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": NSE}

def _ts(s):
    for f in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try: return dt.datetime.strptime(s, f)
        except Exception: pass
    return dt.datetime.now()

def fetch_all(days=7):
    s = requests.Session(); s.get(NSE, headers=H, timeout=10)
    to, fr = dt.date.today(), dt.date.today() - dt.timedelta(days=days)
    out = []
    for sym in PORTFOLIO:
        try:
            r = s.get(f"{NSE}/api/corporate-announcements", headers=H, timeout=15, params={
                "index": "equities", "symbol": sym,
                "from_date": fr.strftime("%d-%m-%Y"), "to_date": to.strftime("%d-%m-%Y")})
            rows = r.json() if r.ok else []
        except Exception:
            rows = []
        for a in rows:
            out.append({"id": hashlib.md5((sym + a.get("attchmntFile", "") + a["an_dt"]).encode()).hexdigest()[:12],
                        "symbol": sym, "type": a["desc"], "text": a.get("attchmntText", ""),
                        "pdf": a.get("attchmntFile"), "ts": _ts(a["an_dt"]).isoformat()})
    if not out: raise RuntimeError("no announcements")
    return out

# ---------- classification: NSE's own 'desc' is unreliable (results often arrive as "Outcome of Board Meeting")
# so we read type + text. Ordered rules, first match wins: (label, category, priority, regex)
_RULES = [
 ("Upcoming Board Meeting", "Corporate Actions", 3, r"intimation of board meeting|prior intimation|board meeting (is |will be )?(scheduled|to be held)|date of board meeting"),
 ("Routine Filing", "Other", 4, r"newspaper|publication|advertisement|shareholding pattern|investor complaints|compliance certificate|trading window|share certificate|loss of|closure of|duplicate"),
 ("RESULTS", "Results", 1, r"financial results?|(un)?audited .*results?|results? for the (quarter|period|year|half)|results? of the (quarter|period|year|half)"),
 ("Management Change", "Management", 1, r"appoint|resign|cessation|director|key managerial|kmp|chief (financial|executive|operating|technology)|\bcfo\b|\bceo\b|company secretary"),
 ("Credit Rating", "Ratings", 2, r"credit rating|\brating\b|crisil|icra|care ratings|india ratings"),
 ("Acquisition / Deal", "M&A", 1, r"acqui|merger|amalgam|takeover|\bstake\b|joint venture|scheme of arrangement|divest"),
 ("Dividend", "Corporate Actions", 2, r"dividend"),
 ("Fund Raise", "Corporate Actions", 2, r"fund ?rais|\bncds?\b|debenture|\bqip\b|rights issue|preferential|bonds?\b"),
 ("Order Win", "Business Updates", 2, r"(order|contract)s? (worth|valued|of rs)|\bbags\b|awarded|letter of (award|intent)|work order"),
 ("Investor Update", "Investor Meets", 3, r"investor meet|analyst|institutional investor|earnings call|concall|conference call|investor presentation|transcript"),
 ("Business Update", "Business Updates", 3, r"press release|launch|usfda|approval|capacity|commission"),
 ("Board Outcome", "Corporate Actions", 2, r"outcome of board|board meeting"),
]
CATS = ["Results", "Management", "M&A", "Corporate Actions", "Business Updates", "Ratings", "Investor Meets", "Other"]
_MON = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}

def period(text):
    """'quarter ended 30 Sep 2026' / 'period ended September 30, 2026' -> ('Q2 FY27', annual?)"""
    m = re.search(r"(?:quarter|period|year|half[ -]year)\s+ended\s+(?:on\s+)?(?:(\d{1,2})(?:st|nd|rd|th)?[\s,-]+([A-Za-z]{3,9})[\s,.-]+(\d{4})|([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}))", text, re.I)
    if not m: return None, False, None
    mon = (m.group(2) or m.group(4))[:3].lower(); yr = int(m.group(3) or m.group(6))
    mo = _MON.get(mon)
    if not mo: return None, False, None
    fy = str(yr + 1 if mo >= 4 else yr)[2:]
    annual = bool(re.search(r"year ended", text, re.I)) and not re.search(r"quarter|half", text, re.I)
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(mo)
    return (f"FY{fy}" if annual else (f"Q{q} FY{fy}" if q else None)), annual, f"{mon.title()} {yr}"

def classify(a):
    blob = f'{a["type"]} {a.get("text", "")}'.lower()
    label, cat, pr = next(((l, c, p) for l, c, p, rx in _RULES if re.search(rx, blob)), ("Routine Filing", "Other", 4))
    per, annual, pend = (None, False, None)
    if label == "RESULTS":
        per, annual, pend = period(a.get("text", "") + " " + a["type"])
        label = "Annual Results" if annual else "Quarterly Results"
    return {"label": label, "cat": cat, "prio": pr, "period": per, "period_end": pend, "is_results": cat == "Results"}

def prep(items):
    items = [dict(a, **classify(a)) for a in items]
    return sorted(items, key=lambda x: (x["prio"], -dt.datetime.fromisoformat(x["ts"]).timestamp()))

# ---------- plain-English one-liners
_BOILER = [r"^.*?\b(has|have)\s+(submitted|informed|intimated|filed|enclosed)\b[^,]*?(exchange|exchanges)[,\s]*(that|regarding|the|a)?\s*",
           r"pursuant to regulation[^,]*?,\s*", r"this is to (inform|intimate)( you)?( that)?\s*", r"we wish to inform( you)?( that)?\s*",
           r"\b(sebi|listing)\s*\(.*?\)\s*regulations?,?\s*\d*\s*"]
def plain(text, n=120):
    t = re.sub(r"\s+", " ", text or "").strip()
    for b in _BOILER: t = re.sub(b, "", t, flags=re.I)
    t = t.strip(" ,.;:-")
    t = t[:1].upper() + t[1:]
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"

def _llm_line(a):  # optional cheap-model rewrite (set ANTHROPIC_API_KEY); cached by caller
    import anthropic
    m = anthropic.Anthropic().messages.create(model=os.getenv("FINN_MODEL", "claude-haiku-5-5"), max_tokens=60,
        messages=[{"role": "user", "content": "Rewrite this stock-exchange filing as ONE plain-English line (max 16 words) for an investor. "
                   "State what happened; no boilerplate, no company-name prefix.\n\n" + a["type"] + ": " + a["text"]}])
    return m.content[0].text.strip()

def one_liner(a):
    if os.getenv("ANTHROPIC_API_KEY") and not os.getenv("FINN_DEMO"):
        try: return _llm_line(a)
        except Exception: pass
    return plain(a.get("text") or a["type"])

def _verb(p):
    if p is None: return None
    return "jumped" if p >= 20 else "rose" if p >= 0 else "fell" if p > -20 else "slumped"

def headline(a, r):
    if a["cat"] != "Results":
        return one_liner(a)
    per = a.get("period") or "latest period"
    if not r:
        return f"{per} results filed. Numbers being parsed."
    rev, pat = r["revenue"], r["pat"]
    bits = []
    for name, m in (("Revenue", rev), ("PAT", pat)):
        p, base = (m["yoy"], "YoY") if m["yoy"] is not None else (m["qoq"], "QoQ")
        if p is not None: bits.append(f"{name} {_verb(p)} {abs(p):.1f}% {base}")
    return f"{per}: " + ", ".join(bits) if bits else f"{per} results filed"

_cache = {}
def cached(key, ttl, fn):
    t, v = _cache.get(key, (0, None))
    if v is None or time.time() - t > ttl:
        v = fn(); _cache[key] = (time.time(), v)
    return v

def screener_url(sym, annual=False):
    return f"https://www.screener.in/company/{sym}/consolidated/#{'profit-loss' if annual else 'quarters'}"
