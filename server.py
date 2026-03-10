import os
import time
import requests
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from runScreening import get_tickers, _screen_batch

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# -- Telegram helpers --

def send_telegram(text):
    """Send message via Telegram Bot API (MarkdownV2)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    # Split long messages (Telegram limit: 4096 chars)
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            requests.post(url, data={
                "chat_id": CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
            }, timeout=10)
        except Exception as e:
            log.error(f"Telegram send failed: {e}")


def format_report(market, cond_d, cond_m, index_map=None):
    """Format screening results as an HTML Telegram message."""
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
    lines = [f"<b>[StockAlarm] {market} Screening</b>", f"<i>{now}</i>", ""]

    if not cond_d:
        lines.append("Condition D: No candidates found.")
        return "\n".join(lines)

    # Group by index for display
    if index_map:
        grouped_d = {}
        for t in cond_d:
            idx = index_map.get(t, "Other")
            grouped_d.setdefault(idx, []).append(t)
        lines.append(f"<b>Condition D ({len(cond_d)}):</b>")
        for idx_name in ["S&P 500", "NDQ 100", "Russell 2000", "Other"]:
            if idx_name in grouped_d:
                lines.append(f"  <b>[{idx_name}]</b> {', '.join(grouped_d[idx_name])}")
    else:
        lines.append(f"<b>Condition D ({len(cond_d)}):</b> {', '.join(cond_d)}")
    lines.append("")

    if cond_m:
        if index_map:
            grouped_m = {}
            for ticker, rsi, stk in cond_m:
                idx = index_map.get(ticker, "Other")
                grouped_m.setdefault(idx, []).append((ticker, rsi, stk))
            lines.append(f"<b>Condition M Final ({len(cond_m)}):</b>")
            for idx_name in ["S&P 500", "NDQ 100", "Russell 2000", "Other"]:
                if idx_name in grouped_m:
                    lines.append(f"  <b>[{idx_name}]</b>")
                    for ticker, rsi, stk in grouped_m[idx_name]:
                        lines.append(f"    {ticker}: RSI {rsi:.1f} / StochK {stk:.1f}")
        else:
            lines.append(f"<b>Condition M Final ({len(cond_m)}):</b>")
            for ticker, rsi, stk in cond_m:
                lines.append(f"  {ticker}: RSI {rsi:.1f} / StochK {stk:.1f}")
    else:
        lines.append("Condition M: No final targets.")

    return "\n".join(lines)


# -- Ticker fetchers (override for US to exclude hardcoded list) --

def _normalize_ticker(t):
    return str(t).replace(".", "-").strip()


def get_tickers_us():
    """S&P 500 + NASDAQ 100 + Russell 2000 (top 1000). Returns (tickers, index_map)."""
    import pandas as pd
    import io
    headers = {"User-Agent": "Mozilla/5.0"}

    sp500_set = set()
    ndx100_set = set()
    russell_set = set()

    # S&P 500
    try:
        res = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=headers, timeout=10,
        )
        tables = pd.read_html(io.StringIO(res.text))
        if tables:
            sp = [_normalize_ticker(t) for t in tables[0]["Symbol"].tolist()
                  if isinstance(t, (str, float)) and str(t) != "nan"]
            sp500_set = set(sp)
            log.info(f"S&P 500: {len(sp500_set)} tickers")
    except Exception as e:
        log.warning(f"S&P 500 fetch failed: {e}")

    # NASDAQ 100
    try:
        res = requests.get(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            headers=headers, timeout=10,
        )
        tables = pd.read_html(io.StringIO(res.text))
        for df in tables:
            col = "Ticker" if "Ticker" in df.columns else ("Symbol" if "Symbol" in df.columns else None)
            if col:
                ndx = [_normalize_ticker(t) for t in df[col].tolist()
                       if isinstance(t, (str, float)) and str(t) != "nan"]
                ndx100_set = set(ndx)
                log.info(f"NASDAQ 100: {len(ndx100_set)} tickers")
                break
    except Exception as e:
        log.warning(f"NASDAQ 100 fetch failed: {e}")

    # Russell 2000 (top 1000 by weight from iShares IWM)
    try:
        iwm_url = "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
        iwm_res = requests.get(iwm_url, headers=headers, timeout=15)
        lines = iwm_res.text.splitlines()
        header_idx = None
        for idx, line in enumerate(lines):
            if line.startswith('"Ticker"') or line.startswith("Ticker"):
                header_idx = idx
                break
        if header_idx is not None:
            csv_text = "\n".join(lines[header_idx:])
            iwm_df = pd.read_csv(io.StringIO(csv_text))
            iwm_df["Ticker"] = iwm_df["Ticker"].astype(str).str.strip().str.strip('"')
            iwm_df = iwm_df[iwm_df["Ticker"].apply(lambda t: t.isalpha() and len(t) <= 5)]
            iwm_top = [_normalize_ticker(t) for t in iwm_df.head(1000)["Ticker"].tolist()]
            russell_set = set(iwm_top)
            log.info(f"Russell 2000 (top 1000): {len(russell_set)} tickers")
    except Exception as e:
        log.warning(f"Russell 2000 fetch failed: {e}")

    # Build index_map: priority S&P 500 > NASDAQ 100 > Russell 2000
    all_tickers = sp500_set | ndx100_set | russell_set
    index_map = {}
    for t in all_tickers:
        if t in sp500_set:
            index_map[t] = "S&P 500"
        elif t in ndx100_set:
            index_map[t] = "NDQ 100"
        else:
            index_map[t] = "Russell 2000"

    return sorted(all_tickers), index_map


# -- Screening runner --

def run_screening(market):
    """Run the two-step screening and return (cond_d, cond_m_details, index_map)."""
    index_map = None
    if market == "US":
        tickers, index_map = get_tickers_us()
    else:
        tickers = get_tickers("KR")

    log.info(f"[{market}] Screening {len(tickers)} tickers...")

    # Step 1: Daily
    cond_d = _screen_batch(tickers, "2y", "1d", "Condition D", min_bars=100)

    if not cond_d:
        return [], [], index_map

    # Step 2: 15-min intraday
    # Collect detailed results for reporting
    import yfinance as yf
    from runScreening import get_fearzone_condition, get_stoch_k, rsi as calc_rsi

    cond_m = []
    try:
        df_batch = yf.download(cond_d, period="60d", interval="15m", progress=False, group_by="ticker")
        if not df_batch.empty:
            for ticker in cond_d:
                try:
                    if len(cond_d) > 1:
                        if ticker not in df_batch.columns.levels[0]:
                            continue
                        df = df_batch[ticker].dropna(how="all")
                    else:
                        df = df_batch.dropna(how="all")
                    if df.empty or len(df) < 100:
                        continue
                    df = get_fearzone_condition(df)
                    df["RSI"] = calc_rsi(df["Close"], length=14)
                    df["Stoch_K"] = get_stoch_k(df)
                    if "FearZone_Con" not in df.columns:
                        continue
                    last = df.iloc[-1]
                    if (bool(last["FearZone_Con"]) and
                        not __import__("pandas").isna(last["RSI"]) and last["RSI"] <= 31 and
                        not __import__("pandas").isna(last["Stoch_K"]) and last["Stoch_K"] <= 21):
                        cond_m.append((ticker, float(last["RSI"]), float(last["Stoch_K"])))
                except Exception:
                    continue
    except Exception as e:
        log.error(f"Step 2 batch error: {e}")

    return cond_d, cond_m, index_map


# -- Market hours check --

def get_active_markets():
    """Return list of active markets ('US', 'KR') based on current market hours."""
    now_et = datetime.now(ZoneInfo("America/New_York"))
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    active = []

    # KR market: Mon-Fri, 09:00 ~ 15:00 KST
    if now_kst.weekday() < 5:
        kr_start = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
        kr_end = now_kst.replace(hour=15, minute=0, second=0, microsecond=0)
        if kr_start <= now_kst <= kr_end:
            active.append("KR")

    # US market: Mon-Fri, 09:30 ~ 16:00 ET
    if now_et.weekday() < 5:
        us_start = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        us_end = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        if us_start <= now_et <= us_end:
            active.append("US")

    return active


def seconds_until_next_market():
    """Return seconds until next market open."""
    now_et = datetime.now(ZoneInfo("America/New_York"))
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))

    candidates = []

    # Next KR open
    kr_open = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
    if now_kst >= kr_open:
        from datetime import timedelta
        kr_open += timedelta(days=1)
    # Skip weekends
    while kr_open.weekday() >= 5:
        from datetime import timedelta
        kr_open += timedelta(days=1)
    candidates.append((kr_open - now_kst).total_seconds())

    # Next US open
    us_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    if now_et >= us_open:
        from datetime import timedelta
        us_open += timedelta(days=1)
    while us_open.weekday() >= 5:
        from datetime import timedelta
        us_open += timedelta(days=1)
    candidates.append((us_open - now_et).total_seconds())

    return max(60, min(candidates))


# -- Main loop --

def main():
    log.info("StockAlarm server started.")
    send_telegram("<b>[StockAlarm] Server started.</b>")

    INTERVAL = 15 * 60  # 15 minutes

    while True:
        markets = get_active_markets()

        if not markets:
            wait = seconds_until_next_market()
            wait_min = int(wait // 60)
            log.info(f"Markets closed. Sleeping {wait_min} min until next open.")
            time.sleep(min(wait, 1800))  # Wake up every 30 min max to re-check
            continue

        for market in markets:
            log.info(f"[{market}] Market is open. Running screening...")
            try:
                cond_d, cond_m, index_map = run_screening(market)
                report = format_report(market, cond_d, cond_m, index_map)
                send_telegram(report)
                log.info(f"[{market}] Report sent. D={len(cond_d)}, M={len(cond_m)}")
            except Exception as e:
                log.error(f"[{market}] Screening error: {e}")
                send_telegram(f"<b>[StockAlarm] {market} Error:</b> {e}")

        log.info(f"Sleeping {INTERVAL // 60} min...")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
