"""Sample data so the demo never dies if Yahoo/NSE block the server. UI labels it 'sample'."""
import numpy as np, pandas as pd, datetime as dt, hashlib
from config import PORTFOLIO
from results import derive

def prices(n=60):
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    rets = rng.normal(0.0004, 0.013, (n, len(PORTFOLIO)))
    df = pd.DataFrame(100 * (1 + rets).cumprod(0), index=idx, columns=list(PORTFOLIO))
    df.loc[idx[:-4], "JPL"] = np.nan   # listed ~4 sessions ago
    return df

_R = {
 "ITC": derive(dict(revenue=21500, ebitda=8100, pbt=7800, pat=5900, eps=4.7),
               dict(revenue=20700, ebitda=7900, pbt=7600, pat=5700, eps=4.6),
               dict(revenue=20400, ebitda=7600, pbt=7300, pat=5600, eps=4.5)),
 "JPL": derive(dict(revenue=36500, ebitda=18200, pbt=9100, pat=6900, eps=10.4),
               dict(revenue=35100, ebitda=17300, pbt=8500, pat=6500, eps=9.8),
               dict(revenue=30200, ebitda=14900, pbt=7000, pat=5400, eps=8.3)),
 "TCS": derive(dict(revenue=65800, ebitda=16900, pbt=16200, pat=12300, eps=34.0),
               dict(revenue=64200, ebitda=16400, pbt=15700, pat=12000, eps=33.1),
               dict(revenue=63400, ebitda=16000, pbt=15100, pat=11900, eps=32.9)),
}
_A = [  # symbol, type, text, prio, hours_ago
 ("JPL", "Financial Results", "Unaudited consolidated results for the quarter ended 30 Sep 2026", 1, 20),
 ("TCS", "Financial Results", "Results for the quarter ended 30 Sep 2026; interim dividend recommended", 1, 30),
 ("INFY", "Change in Directors/KMP", "Appointment of new Chief Financial Officer effective 1 Dec 2026", 1, 6),
 ("LT", "Acquisition", "Agrees to acquire 51% stake in a data-centre EPC firm", 1, 40),
 ("BEL", "Outcome of Board Meeting", "Board approves capex plan; fund raise via NCDs", 2, 12),
 ("ITC", "Outcome of Board Meeting", "ITC Limited has submitted to the Exchange, the financial results for the period ended September 30, 2026.", 0, 14),
 ("ITC", "Dividend", "Record date fixed for interim dividend", 2, 55),
 ("HDFCBANK", "Credit Rating", "CRISIL reaffirms AAA/Stable on bonds", 2, 70),
 ("RELIANCE", "Analysts/Institutional Investor Meet", "Schedule of investor meet", 3, 10),
 ("NTPC", "Investor Presentation", "Q2 FY27 investor presentation", 3, 28),
 ("M&M", "Press Release", "Launches new SUV platform", 4, 3),
 ("NMDC", "Trading Window", "Closure of trading window", 4, 8),
 ("ASHOKLEY", "Newspaper Publication", "Publication of results notice", 4, 22),
 ("MOLBIO", "Loss of Share Certificate", "Issue of duplicate share certificate", 4, 36),
 ("SUNPHARMA", "Press Release", "USFDA approval for generic formulation", 4, 90),
 ("POWERGRID", "Outcome of Board Meeting", "Approves investment in transmission project", 2, 100),
 ("HINDUNILVR", "Change in Directors/KMP", "Re-appointment of independent director", 1, 120),
]
def announcements():
    now = dt.datetime.now(); out = []
    for s, t, x, p, h in _A:
        out.append({"id": hashlib.md5((s + t + x).encode()).hexdigest()[:12], "symbol": s, "type": t,
                    "text": x, "pdf": None, "ts": (now - dt.timedelta(hours=h)).isoformat()})
    return out

def results(sym): return _R.get(sym)

_FUND = {"pe": 24.1, "pb": 4.2, "roe": 17.5, "de": 0.4, "mcap": 250000}
def fundamentals(sym): return dict(_FUND, sample=True)
