import yfinance as yf
import pandas as pd
import numpy as np
import argparse
import requests
import io
import warnings
import time
import logging

# Suppress yfinance "delisted" noise and FutureWarnings
warnings.filterwarnings("ignore", category=FutureWarning)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

def manual_wma(series, length):
    vals = series.values.astype(float)
    if len(vals) < length:
        return pd.Series(np.nan, index=series.index)
    w = np.arange(1, length + 1, dtype=float)
    w = w / w.sum()
    conv = np.convolve(vals, w[::-1], mode='valid')
    result = np.full(len(vals), np.nan)
    result[length - 1:] = conv
    return pd.Series(result, index=series.index)

def rsi(close, length=14):
    """Calculate RSI (Relative Strength Index)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/length, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1/length, min_periods=length).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def stoch(high, low, close, k=40, smooth_k=10):
    """Calculate Slow Stochastic %K."""
    lowest_low = low.rolling(window=k).min()
    highest_high = high.rolling(window=k).max()
    raw_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    stoch_k = raw_k.rolling(window=smooth_k).mean()
    return stoch_k


def get_fearzone_condition(df, high_period=30, stdev_period=50):
    # Ensure columns are simple strings
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Check if necessary columns exist
    if 'Close' not in df.columns or 'High' not in df.columns:
        return df

    close = df['Close'].astype(float)
    high = df['High'].astype(float)
    
    # FZ1 Calculation
    highest_high = high.rolling(window=high_period).max()
    df['FZ1'] = (highest_high - close) / highest_high
    avg1 = manual_wma(df['FZ1'], stdev_period)
    stdev1 = df['FZ1'].rolling(window=stdev_period).std()
    df['FZ1_Limit'] = avg1 + stdev1

    # FZ2 Calculation
    df['FZ2'] = manual_wma(close, high_period)
    avg2 = manual_wma(df['FZ2'], stdev_period)
    stdev2 = df['FZ2'].rolling(window=stdev_period).std()
    df['FZ2_Limit'] = avg2 - stdev2

    df['FearZone_Con'] = (df['FZ1'] > df['FZ1_Limit']) & (df['FZ2'] < df['FZ2_Limit'])
    return df

def get_stoch_k(df, k=40, smooth_k=10):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    if 'High' not in df.columns or 'Low' not in df.columns or 'Close' not in df.columns:
        return pd.Series(np.nan, index=df.index)
        
    return stoch(df['High'], df['Low'], df['Close'], k=k, smooth_k=smooth_k)

def get_tickers_kr():
    print("Fetching KOSPI 200 + KOSDAQ 150 tickers...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    tickers = []

    # KOSPI 200 from Wikipedia
    try:
        url = 'https://en.wikipedia.org/wiki/KOSPI_200'
        res = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(io.StringIO(res.text))
        for t in tables:
            if 'Symbol' in t.columns and len(t) >= 100:
                kospi_syms = t['Symbol'].dropna().astype(str).tolist()
                kospi_tickers = [s.zfill(6) + ".KS" for s in kospi_syms]
                tickers.extend(kospi_tickers)
                print(f"  KOSPI 200: {len(kospi_tickers)} tickers loaded")
                break
    except Exception as e:
        print(f"Warning: KOSPI 200 fetch failed ({e})")

    # KOSDAQ 150 from Naver (top 150 by market cap)
    kosdaq_tickers = []
    for page in range(1, 5):
        try:
            url = f"https://m.stock.naver.com/api/stocks/marketValue/KOSDAQ?page={page}&pageSize=50"
            res = requests.get(url, timeout=10)
            data = res.json()
            if not data.get('stocks'):
                break
            for stock in data['stocks']:
                kosdaq_tickers.append(stock['itemCode'] + ".KQ")
            if len(kosdaq_tickers) >= 150:
                break
        except Exception as e:
            print(f"Warning: KOSDAQ page {page} fetch failed ({e})")
            break
    kosdaq_tickers = kosdaq_tickers[:150]
    tickers.extend(kosdaq_tickers)
    print(f"  KOSDAQ 150: {len(kosdaq_tickers)} tickers loaded")

    return list(set(tickers))

def get_tickers(market='US'):
    if market.upper() == 'KR':
        return get_tickers_kr()
        
    print("Fetching US tickers from reliable sources...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # Base Ticker List (growth, momentum, thematic, ETFs)
    tickers = [
        # Growth / Fintech / Tech
        "HIMS", "SOFI", "PLTR", "UPST", "COIN", "DKNG", "MARA", "RIOT", "AFRM", "OPEN",
        "AI", "PATH", "SE", "MELI", "U", "SNOW", "CRWD", "DDOG", "NET", "OKTA",
        "ZS", "ASAN", "MDB", "TEAM", "DOCU", "ZM", "PTON", "ROKU", "SHOP", "PYPL",
        "ABNB", "UBER", "LYFT", "DASH", "ETSY", "CHWY", "TDOC", "CVNA",
        # Meme / Speculative
        "GME", "AMC", "BB", "NOK", "PLUG", "FCEL", "BLDP", "QS", "CHPT", "BE",
        # EV
        "NIO", "XPEV", "LI", "RIVN", "LCID", "NKLA", "HYLN", "WKHS",
        # SPACs / Small-cap
        "CLOV", "CLNE", "GEVO", "PSFE", "PAYO",
        # Quantum / AI
        "IONQ", "RGTI", "QUBT", "QBTS", "BBAI", "SOUN",
        # Gaming / Casinos
        "GENI", "PENN", "WYNN", "LVS", "MGM", "CZR", "BYD", "BALY", "GDEN", "RRR",
        "MCRI", "CHDN",
        # Materials / Mining / Uranium
        "GT", "ALB", "SQM", "LAC", "LIT", "MP", "REMX", "COPX",
        "URA", "URNM", "CCJ", "UUUU", "NXE", "DNN", "UEC",
        "FCX", "SCCO", "VALE", "RIO", "BHP",
        # Precious Metals
        "NEM", "GOLD", "AU", "KGC", "AEM", "PAAS", "HL", "AG", "FSM", "EXK",
        "WPM", "FNV", "OR", "RGLD",
        # ETFs - Broad
        "SLV", "GLD", "GDX", "GDXJ", "SIL", "SILJ",
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VEU", "VWO", "EEM", "EFA",
        # ETFs - Sector
        "XLF", "XLK", "XLV", "XLY", "XLP", "XLI", "XLE", "XLB", "XLU", "XLRE",
        "KRE", "XBI", "IBB", "SMH", "SOXX", "XRT", "XME",
        # ETFs - International / Thematic
        "KWEB", "FXI", "MCHI",
        "ARKK", "ARKW", "ARKF", "ARKG", "ARKQ", "ARKX",
        "BITO", "GBTC", "ETHE",
    ]
    
    # S&P 500
    try:
        sp500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        sp500_res = requests.get(sp500_url, headers=headers)
        sp500_tables = pd.read_html(io.StringIO(sp500_res.text))
        if sp500_tables:
            tickers.extend(sp500_tables[0]['Symbol'].tolist())
    except Exception as e:
        print(f"Warning: S&P 500 fetch failed ({e})")

    # NDX 100
    try:
        ndx100_url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
        ndx100_res = requests.get(ndx100_url, headers=headers)
        ndx100_tables = pd.read_html(io.StringIO(ndx100_res.text))
        for df in ndx100_tables:
            if 'Ticker' in df.columns:
                tickers.extend(df['Ticker'].tolist())
                break
            elif 'Symbol' in df.columns:
                tickers.extend(df['Symbol'].tolist())
                break
    except Exception as e:
        print(f"Warning: NDX 100 fetch failed ({e})")

    # Russell 2000 (IWM holdings from iShares)
    try:
        iwm_url = 'https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund'
        iwm_res = requests.get(iwm_url, headers=headers, timeout=15)
        # Skip metadata rows at the top, find the header row with "Ticker"
        lines = iwm_res.text.splitlines()
        header_idx = None
        for idx, line in enumerate(lines):
            if line.startswith('"Ticker"') or line.startswith('Ticker'):
                header_idx = idx
                break
        if header_idx is not None:
            csv_text = '\n'.join(lines[header_idx:])
            iwm_df = pd.read_csv(io.StringIO(csv_text))
            iwm_tickers = iwm_df['Ticker'].dropna().tolist()
            # Filter out non-equity rows (like cash, futures)
            iwm_tickers = [t.strip().strip('"') for t in iwm_tickers if isinstance(t, str) and t.strip().strip('"').isalpha()]
            tickers.extend(iwm_tickers)
            print(f"  Russell 2000 (IWM): {len(iwm_tickers)} tickers loaded")
    except Exception as e:
        print(f"Warning: Russell 2000 fetch failed ({e})")

    # Cleanup Tickers
    unique_tickers = sorted(list(set([str(t).replace('.', '-').strip() for t in tickers if isinstance(t, (str, float)) and str(t) != 'nan'])))
    return unique_tickers

def _resample_to_4h(df):
    """Resample 1h OHLCV data to 4h candles, chunking from start of each trading day."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Close'])
    # Assign group IDs: restart counting at each new trading day
    dates = df.index.date
    group_ids = []
    current_group = 0
    count_in_day = 0
    prev_date = None
    for d in dates:
        if d != prev_date:
            # New day: start fresh group
            if count_in_day % 4 != 0 and prev_date is not None:
                current_group += 1  # close partial group from previous day
            count_in_day = 0
            prev_date = d
        if count_in_day > 0 and count_in_day % 4 == 0:
            current_group += 1
        group_ids.append(current_group)
        count_in_day += 1
    resampled = df.groupby(group_ids).agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    })
    # Use the first timestamp of each group as index
    first_idx = df.groupby(group_ids).apply(lambda x: x.index[0])
    resampled.index = first_idx.values
    return resampled

def _screen_batch(tickers, period, interval, step_label, resample_4h=False, min_bars=100):
    """Run FearZone + RSI + StochK screening on a list of tickers."""
    results = []
    batch_size = 200
    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]
    num_batches = len(batches)

    for batch_idx, batch in enumerate(batches):
        print(f"Processing batch {batch_idx + 1}/{num_batches}...")
        try:
            df_batch = yf.download(batch, period=period, interval=interval, progress=False, group_by='ticker')
            if df_batch.empty:
                continue
        except Exception as e:
            print(f"Error in batch {batch_idx + 1}: {e}")
            continue
        for ticker in batch:
            try:
                if len(batch) > 1:
                    if ticker not in df_batch.columns.levels[0]:
                        continue
                    df = df_batch[ticker].dropna(how='all')
                else:
                    df = df_batch.dropna(how='all')
                if resample_4h and not df.empty:
                    df = _resample_to_4h(df)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                if df.empty or len(df) < min_bars:
                    continue
                # RSI pre-check: skip expensive FearZone if RSI > 31
                rsi_vals = rsi(df['Close'], length=14)
                if rsi_vals.empty or pd.isna(rsi_vals.iloc[-1]) or rsi_vals.iloc[-1] > 31:
                    continue
                df = get_fearzone_condition(df)
                df['RSI'] = rsi_vals
                df['Stoch_K'] = get_stoch_k(df)
                if 'FearZone_Con' not in df.columns or df['FearZone_Con'].isna().all():
                    continue
                last_row = df.iloc[-1]
                if (bool(last_row['FearZone_Con']) == True and
                    not pd.isna(last_row['RSI']) and last_row['RSI'] <= 31 and
                    not pd.isna(last_row['Stoch_K']) and last_row['Stoch_K'] <= 21):
                    results.append(ticker)
                    print(f" [Found {step_label}] {ticker} (RSI: {last_row['RSI']:.2f}, StochK: {last_row['Stoch_K']:.2f})")
            except Exception:
                continue
    return results

def screen_stocks(market='US', timeframe='d'):
    tickers = get_tickers(market)
    print(f"Total unique tickers to screen ({market}): {len(tickers)}")

    # Timeframe config
    resample_4h = False
    if timeframe == 'h':
        step1_period, step1_interval = "60d", "1h"
        step1_label = "4H"
        resample_4h = True
    else:
        step1_period, step1_interval = "2y", "1d"
        step1_label = "Daily"

    step1_min_bars = 50 if resample_4h else 100
    print(f"\nStep 1: {step1_label} Screening (Condition D) [{'4h' if resample_4h else step1_interval}]")
    candidates_d = _screen_batch(tickers, step1_period, step1_interval, "Condition D", resample_4h=resample_4h, min_bars=step1_min_bars)

    if not candidates_d:
        print("\nNo stocks found satisfying Condition D.")
        return

    print(f"\nStep 2: Intraday Screening (Condition M) [15m] for {len(candidates_d)} candidates")
    final_targets = _screen_batch(candidates_d, "60d", "15m", "Condition M")

    print("\n" + "="*40)
    print(f"SCREENING RESULTS ({market}, timeframe={timeframe})")
    print("="*40)
    print(f"Condition D Candidates ({len(candidates_d)}): {candidates_d}")
    print(f"Condition M Final Targets ({len(final_targets)}): {final_targets}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock screener", add_help=False)
    parser.add_argument("--help", action="help", help="Show this help message and exit")
    parser.add_argument("-country", type=str, default="US", choices=["US", "KR"],
                        help="Market to screen: US or KR (default: US)")
    parser.add_argument("-h", dest="timeframe", type=str, default="d", choices=["d", "h"],
                        help="Timeframe: d=daily/15m (default), h=1h/15m")
    args = parser.parse_args()

    start_total = time.time()
    screen_stocks(args.country.upper(), args.timeframe)
    end_total = time.time()
    print(f"\nTotal screening time: {end_total - start_total:.2f} seconds")

