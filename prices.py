import pandas as pd
from config import PORTFOLIO

WINDOWS = {"1D": 1, "1W": 5, "1M": 21}

def load_prices(days=60):
    import yfinance as yf
    t = [f"{s}.NS" for s in PORTFOLIO]
    df = yf.download(t, period=f"{days}d", auto_adjust=True, progress=False)
    close = df["Close"]
    close.columns = [c.removesuffix(".NS") for c in close.columns]
    empty = [c for c in close if close[c].dropna().empty]
    if empty: print("NO DATA (check ticker):", empty)
    close = close.dropna(axis=1, how="all")
    if close.empty: raise RuntimeError("no price data")
    return close

def stock_returns(close, lb):
    """% return over lb sessions. Stocks lacking a start-of-window price (new listings) -> NaN + flag."""
    w = close.iloc[-(lb + 1):]
    r = (w.iloc[-1] / w.iloc[0] - 1) * 100
    short = w.iloc[0].isna()
    return r.where(~short), short

def ew_performance(close, lb):
    """Equal-weight, daily-rebalanced: mean of available daily returns, compounded."""
    dr = close.pct_change().iloc[-lb:] if lb > 1 else close.pct_change().iloc[-1:]
    idx = (1 + dr.mean(axis=1)).cumprod()
    return (idx.iloc[-1] - 1) * 100, idx * 100

def movers(r, n_min=3, n_max=5, k=1.0):
    """Top n gainers/losers, n in [3,5]; shrinks to 'top x' only if the rest clearly lag."""
    r = r.dropna().sort_values(ascending=False)
    cut = r.std() * k
    n_up = int(((r - r.median()) > cut).sum())
    n_dn = int(((r - r.median()) < -cut).sum())
    clip = lambda n: max(n_min, min(n_max, n))
    return r.head(clip(n_up)), r.tail(clip(n_dn)).sort_values()
