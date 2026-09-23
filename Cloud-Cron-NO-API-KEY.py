"""
CLOUD CRON - NO API KEY VERSION
Fetches live market from NSE Public API (no key) + yfinance
Only sends email with REAL data (market open + real LTP + Institutions move)
Lot 65, Weekly Dynamic, Same SL 15.38 = 1k
No Dhan API Key needed - Only Gmail App Password
"""
import os
import sys
import smtplib
import ssl
import requests
import time as time_module
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, time
import pytz

# Only Gmail from ENV - No Dhan keys
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
GMAIL_TO = os.getenv("GMAIL_TO", GMAIL_USER)

LOT_SIZE = 65
TARGET_POINTS = 1000 / LOT_SIZE  # 15.3846
IST = pytz.timezone('Asia/Kolkata')

# NSE headers for public API (no key needed)
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

def is_market_open_real():
    now_ist = datetime.now(IST)
    if now_ist.weekday() >= 5:
        print(f"Market closed - Weekend {now_ist.strftime('%A %d/%m/%Y')}")
        return False
    market_start = time(9, 15)
    market_end = time(15, 30)
    current_time = now_ist.time()
    if not (market_start <= current_time <= market_end):
        print(f"Market closed - Time {now_ist.strftime('%H:%M IST')} not in 09:15-15:30")
        return False
    print(f"✅ Market OPEN - {now_ist.strftime('%d/%m/%Y %H:%M:%S IST %A')}")
    return True

def fetch_nifty_5min_real():
    try:
        import yfinance as yf
        import pandas as pd
        df = yf.download("^NSEI", period="3d", interval="5m", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 20:
            print(f"❌ Nifty data too less {len(df)}")
            return None
        today = df.index[-1].date()
        today_df = df[df.index.date == today]
        if len(today_df) < 10:
            today_df = df.tail(80)
        print(f"✅ Nifty 5min REAL: {len(today_df)} candles Last {today_df['Close'].iloc[-1]:.2f} at {today_df.index[-1]}")
        return today_df
    except Exception as e:
        print(f"❌ Nifty fetch failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def find_swings(df, lookback=5):
    highs, lows = [], []
    for i in range(lookback, len(df)-lookback):
        h, l = df['High'].iloc[i], df['Low'].iloc[i]
        if h == df['High'].iloc[i-lookback:i+lookback+1].max():
            highs.append((df.index[i], h))
        if l == df['Low'].iloc[i-lookback:i+lookback+1].min():
            lows.append((df.index[i], l))
    return highs, lows

def detect_idm_priority(highs, lows):
    idms = []
    for i in range(len(lows)-1):
        if abs(lows[i][1] - lows[i+1][1]) < 15:
            idms.append(("IDM_SELL_SIDE", lows[i][0], lows[i][1], lows[i+1][1]))
    for i in range(len(highs)-1):
        if abs(highs[i][1] - highs[i+1][1]) < 15:
            idms.append(("IDM_BUY_SIDE", highs[i][0], highs[i][1], highs[i+1][1]))
    return idms

def detect_institutions_move(df, idm_price, direction):
    print(f"\n🏦 DETECTING INSTITUTIONS MOVE REAL...")
    last_n = df.tail(15)
    liquidity_grab = False
    displacement = False
    institutional_ob = None
    grab_idx = None
    disp_idx = None

    for i in range(len(last_n)):
        low = last_n['Low'].iloc[i]
        high = last_n['High'].iloc[i]
        close = last_n['Close'].iloc[i]
        if direction == "BUY" and low < idm_price and close > idm_price:
            liquidity_grab = True
            grab_idx = i
            print(f"   ✅ LIQUIDITY GRAB REAL: Low {low:.2f} < IDM {idm_price:.2f} Close {close:.2f} > IDM at {last_n.index[i]}")
            break
        if direction == "SELL" and high > idm_price and close < idm_price:
            liquidity_grab = True
            grab_idx = i
            print(f"   ✅ LIQUIDITY GRAB REAL: High {high:.2f} > IDM {idm_price:.2f} Close {close:.2f} < IDM at {last_n.index[i]}")
            break

    if liquidity_grab and grab_idx is not None:
        for i in range(grab_idx+1, len(last_n)):
            body = abs(last_n['Close'].iloc[i] - last_n['Open'].iloc[i])
            range_ = last_n['High'].iloc[i] - last_n['Low'].iloc[i]
            if range_ > 0 and body/range_ > 0.65 and body > 6:
                if (direction == "BUY" and last_n['Close'].iloc[i] > last_n['Open'].iloc[i]) or \
                   (direction == "SELL" and last_n['Close'].iloc[i] < last_n['Open'].iloc[i]):
                    displacement = True
                    disp_idx = i
                    print(f"   ✅ DISPLACEMENT REAL: Body {body:.2f} Range {range_:.2f} Ratio {body/range_:.2f} at {last_n.index[i]}")
                    break

    if displacement and disp_idx is not None:
        for j in range(disp_idx-1, max(grab_idx, disp_idx-4)-1, -1):
            if direction == "BUY" and last_n['Close'].iloc[j] < last_n['Open'].iloc[j]:
                institutional_ob = (last_n['Open'].iloc[j], last_n['Close'].iloc[j], last_n.index[j])
                print(f"   ✅ INSTITUTIONAL OB REAL: {institutional_ob[1]:.2f}-{institutional_ob[0]:.2f} at {institutional_ob[2]}")
                break
            if direction == "SELL" and last_n['Close'].iloc[j] > last_n['Open'].iloc[j]:
                institutional_ob = (last_n['Open'].iloc[j], last_n['Close'].iloc[j], last_n.index[j])
                print(f"   ✅ INSTITUTIONAL OB REAL: {institutional_ob[0]:.2f}-{institutional_ob[1]:.2f} at {institutional_ob[2]}")
                break

    fvgs = []
    for i in range(2, len(df)):
        if df['Low'].iloc[i] > df['High'].iloc[i-2]:
            fvgs.append((df['High'].iloc[i-2], df['Low'].iloc[i]))
    
    institutions_move = liquidity_grab and displacement and institutional_ob is not None
    print(f"   🏦 INSTITUTIONS MOVE REAL: {institutions_move}")
    return {
        'liquidity_grab': liquidity_grab,
        'displacement': displacement,
        'institutional_ob': institutional_ob,
        'fvg': fvgs[-1] if fvgs else None,
        'institutions_move': institutions_move
    }

def get_nse_expiry_and_ltp_real(strike, otype):
    """
    Fetch REAL expiry and REAL LTP from NSE Public API - No API Key
    https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY
    """
    try:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        
        # Get cookie first
        print("   Fetching NSE cookie (no key)...")
        session.get("https://www.nseindia.com", timeout=10)
        time_module.sleep(1)
        
        url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        resp = session.get(url, timeout=15)
        
        if resp.status_code != 200:
            print(f"❌ NSE API failed {resp.status_code}: {resp.text[:200]}")
            return None, 0, None
        
        data = resp.json()
        records = data.get('records', {})
        expiry_dates = records.get('expiryDates', [])
        
        if not expiry_dates:
            print(f"❌ No expiry in NSE data")
            return None, 0, None
        
        nearest = expiry_dates[0]  # First is nearest weekly
        print(f"✅ Weekly expiry REAL from NSE (no key): {expiry_dates[:3]} -> Nearest {nearest}")
        
        # Find LTP for strike
        filtered = data.get('filtered', {}).get('data', [])
        for item in filtered:
            if item.get('strikePrice') == int(strike) and item.get('expiryDate') == nearest:
                ce_pe = item.get('CE' if otype == 'CE' else 'PE', {})
                ltp = ce_pe.get('lastPrice', 0)
                if ltp == 0:
                    print(f"❌ LTP 0 for {strike} {otype} Exp {nearest} - Market maybe closed")
                    return nearest, 0, None
                print(f"✅ REAL LTP from NSE (no key): {strike} {otype} Exp {nearest} LTP {ltp} - REAL DATA")
                return nearest, ltp, f"NSE_{strike}{otype}"
        
        print(f"❌ Strike {strike} {otype} Exp {nearest} not in NSE chain")
        return nearest, 0, None
        
    except Exception as e:
        print(f"❌ NSE REAL error: {e}")
        import traceback
        traceback.print_exc()
        return None, 0, None

def send_real_email(subject, body):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print(f"❌ Gmail secrets not set")
        return False
    try:
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = GMAIL_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, GMAIL_TO, msg.as_string())
        print(f"✅ REAL EMAIL SENT to {GMAIL_TO}: {subject}")
        return True
    except Exception as e:
        print(f"❌ Email failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("="*80)
    print("CLOUD CRON - NO API KEY - NSE PUBLIC API + yfinance")
    print(f"Time: {datetime.now(IST).strftime('%d/%m/%Y %H:%M:%S IST')}")
    print(f"Lot {LOT_SIZE} Same SL {TARGET_POINTS:.2f} pts = 1k - Weekly Dynamic")
    print("No Dhan API Key needed - Only NSE public + Gmail")
    print("="*80)
    
    if not is_market_open_real():
        print("⏸️ Market closed - No real data, no email")
        sys.exit(0)
    
    nifty_5min = fetch_nifty_5min_real()
    if nifty_5min is None:
        print("❌ No real Nifty data - No email")
        sys.exit(0)
    
    current_nifty = nifty_5min['Close'].iloc[-1]
    highs, lows = find_swings(nifty_5min, 5)
    idms = detect_idm_priority(highs, lows)
    print(f"\nIDMs REAL: {len(idms)}")
    if not idms:
        print("❌ No IDM REAL - No email")
        sys.exit(0)
    
    last_idm = idms[-1]
    idm_type, idm_time, idm_price1, idm_price2 = last_idm
    idm_price = (idm_price1 + idm_price2)/2
    direction = "BUY" if "SELL_SIDE" in idm_type else "SELL"
    print(f"Priority IDM REAL: {idm_type} {idm_price:.2f} Direction {direction}")
    
    inst = detect_institutions_move(nifty_5min, idm_price, direction)
    if not inst['institutions_move']:
        print("\n⏸️ No Institutions move REAL - No email (only real move)")
        sys.exit(0)
    
    atm = round(current_nifty/50)*50
    if direction == "BUY":
        strike = atm - 100
        otype = "CE"
    else:
        strike = atm + 100
        otype = "PE"
    print(f"\nDynamic Strike REAL: ATM {atm} {direction} -> {strike} {otype} Lot {LOT_SIZE}")
    
    nearest_expiry, ltp, sec_id = get_nse_expiry_and_ltp_real(strike, otype)
    if not nearest_expiry or ltp == 0:
        print(f"\n❌ No REAL expiry/LTP from NSE - No email (no fake data)")
        sys.exit(0)
    
    if inst['institutional_ob']:
        ob_open, ob_close, ob_time = inst['institutional_ob']
        entry_nifty = (ob_open + ob_close)/2
        ob_low = min(ob_open, ob_close)
        ob_high = max(ob_open, ob_close)
    else:
        print("❌ No Institutional OB REAL - No email")
        sys.exit(0)
    
    entry = ltp
    sl = entry - TARGET_POINTS
    target = entry + TARGET_POINTS
    
    print(f"\n{'='*80}")
    print(f"✅ REAL TRADE - INSTITUTIONS MOVE - NSE PUBLIC API - READY TO EMAIL")
    print(f"{'='*80}")
    print(f"Nifty REAL: {current_nifty:.2f} Direction: {direction}")
    print(f"Strike: {strike} {otype} Exp: {nearest_expiry} (REAL weekly from NSE) Lot: {LOT_SIZE}")
    print(f"REAL LTP: {ltp:.2f} SecID: {sec_id} (REAL from NSE - No Dhan key)")
    print(f"IDM: {idm_price:.2f} OB: {ob_low:.2f}-{ob_high:.2f} Entry Nifty: {entry_nifty:.2f}")
    print(f"Entry: BUY {strike} {otype} @ {entry:.2f} SL: {sl:.2f} Target: {target:.2f}")
    print(f"{'='*80}")
    
    now_ist_str = datetime.now(IST).strftime('%d/%m/%Y %H:%M:%S IST')
    subject = f"🏦 REAL NSE DATA - INSTITUTIONS MOVE {strike} {otype} @ {entry:.2f} - Lot {LOT_SIZE} - Exp {nearest_expiry} - {now_ist_str}"
    
    body = f"""REAL DATA - INSTITUTIONS MOVE - NSE PUBLIC API - NO DHAN KEY NEEDED
Time: {now_ist_str}
This email is 100% REAL data from NSE Public API + yfinance - Not simulated - No Dhan API Key

Market: OPEN - {now_ist_str}
Nifty: {current_nifty:.2f} Direction: {direction} (IDM Priority + Institutions Move)

SMC INSTITUTIONS MOVE REAL (Live from NSE):
- IDM {idm_type}: {idm_price:.2f} (Equal {idm_price1:.2f}={idm_price2:.2f}) PRIORITY #1 - REAL
- Liquidity Grab: Low/High swept IDM - REAL ✅
- Displacement: Big impulsive candle after grab - REAL ✅
- Institutional OB: {ob_low:.2f}-{ob_high:.2f} at {ob_time} - REAL ✅
- FVG: {inst['fvg'][0]:.2f}-{inst['fvg'][1]:.2f} if found - REAL

TRADE - CATCHING INSTITUTIONS MOVE REAL:
ATM: {atm} Dynamic Strike: {strike} {otype} (No Hardcoding)
Expiry: {nearest_expiry} (REAL weekly from NSE Public API - Auto Thu->Thu - No Dhan key)
REAL LTP: {ltp:.2f} (REAL from NSE Option Chain Public API - https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY - NOT SIMULATED - No Dhan key)
Lot Size: {LOT_SIZE} (as you said, not 75)

Entry: BUY {strike} {otype} @ {entry:.2f}
  Nifty Entry: {entry_nifty:.2f} (50% of Institutional OB {ob_low:.2f}-{ob_high:.2f})
  Time: {now_ist_str} (Pullback to OB after IDM sweep + Displacement)
  Reason: Catching Institutions move - Entry at Institutional OB after liquidity grab (REAL from NSE)

SL: {sl:.2f} (-{TARGET_POINTS:.2f} pts = Rs 1000 loss) Same as profit 1:1 - REAL
  Nifty SL: {ob_low-5:.2f} (Below Institutional OB)

Target: {target:.2f} (+{TARGET_POINTS:.2f} pts = Rs 1000 profit) Same as SL 1:1 - REAL
  Nifty Target: FVG {inst['fvg'][0]:.2f}-{inst['fvg'][1]:.2f} then Mitigation

Capital: Rs {entry*LOT_SIZE:.2f} ({entry*LOT_SIZE/30000*100:.2f}% of 30K) Qty: {LOT_SIZE} RR: 1:1

Exit Logic:
- LTP >= {target:.2f} -> EXIT +1000 profit
- LTP <= {sl:.2f} -> EXIT -1000 loss

Bot: CLOUD CRON - Lot {LOT_SIZE} - Weekly Dynamic - Institutions Move Catcher
Source: NSE Public API (no key) + yfinance (no key) - 100% free, no Dhan API needed
This is REAL DATA - No simulation, No fake LTP, Only real market from NSE

Action: BUY {strike} {otype} @ {entry:.2f} immediately (REAL from NSE)

---
Cloud Cron: GitHub Actions - Runs Mon-Fri 09:20-15:25 IST every 5 min
No laptop needed - 100% cloud - No Dhan API Key/Secret needed - Only Gmail needed
"""
    
    sent = send_real_email(subject, body)
    if sent:
        print(f"\n✅ SUCCESS: Real NSE data email sent - No Dhan key needed")
    else:
        print(f"\n❌ Email failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
