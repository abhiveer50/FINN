# FINN (push side)
```
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000      # open http://<ip>:8000 on your phone
FINN_DEMO=1 uvicorn api:app                      # force sample data (offline demo)
```
Live mode: yfinance (prices) + NSE announcements API. If either fails, it falls back to sample data
automatically and the UI shows SAMPLE DATA. Results parsing needs ANTHROPIC_API_KEY (model via FINN_MODEL).
Layout: config (portfolio) | prices (EW perf, movers) | announcements | results (PDF->metrics) | api | static/index.html
