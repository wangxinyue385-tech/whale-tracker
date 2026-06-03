from flask import Flask, request, jsonify, render_template_string
import requests
import os
import datetime
import re
import xml.etree.ElementTree as ET

app = Flask(__name__)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

def get_btc_price():
    try:
        res = requests.get("https://mempool.space/api/v1/prices", timeout=5)
        return res.json().get("USD", 75000)
    except:
        return 75000

# ─── 1. 链上巨鲸转账 ───────────────────────────────────────
def get_whale_txns():
    try:
        res = requests.get("https://mempool.space/api/mempool/recent", timeout=10)
        txns = res.json()
        btc_price = get_btc_price()
        big = []
        for tx in txns:
            btc = tx.get("value", 0) / 1e8
            if btc >= 100:
                usd = round(btc * btc_price)
                big.append({
                    "hash": tx.get("txid", "")[:20] + "...",
                    "btc": round(btc, 2),
                    "usd": usd,
                    "fee": round(tx.get("fee", 0) / 1e8, 6),
                    "alert": btc >= 500
                })
        big.sort(key=lambda x: x["btc"], reverse=True)
        return big[:20]
    except:
        return []

# ─── 2. 成交量异动监控 ─────────────────────────────────────
def get_volume_alerts():
    try:
        # 获取所有币种24h数据
        res = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets"
            "?vs_currency=usd&order=volume_desc&per_page=100&page=1"
            "&sparkline=false&price_change_percentage=24h",
            timeout=10
        )
        coins = res.json()
        alerts = []
        for c in coins:
            vol = c.get("total_volume", 0)
            mcap = c.get("market_cap", 0)
            change = c.get("price_change_percentage_24h") or 0
            # 成交量/市值比 > 0.5 且价格变动 > 5% 视为异动
            if mcap > 0 and vol / mcap > 0.5 and abs(change) > 5:
                alerts.append({
                    "symbol": c.get("symbol", "").upper(),
                    "name": c.get("name", ""),
                    "price": c.get("current_price", 0),
                    "change": round(change, 2),
                    "volume": vol,
                    "mcap": mcap,
                    "vol_mcap_ratio": round(vol / mcap, 2),
                    "alert": abs(change) > 15 or vol / mcap > 1.0
                })
        alerts.sort(key=lambda x: x["vol_mcap_ratio"], reverse=True)
        return alerts[:30]
    except:
        return []

# ─── 3. 合约未平仓量异动 ───────────────────────────────────
def get_oi_alerts():
    try:
        # 用CoinGlass公开API获取OI数据
        symbols = [
            "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
            "DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT",
            "MATICUSDT","LTCUSDT","ATOMUSDT","UNIUSDT","TRXUSDT",
            "NEARUSDT","APTUSDT","OPUSDT","ARBUSDT","SEIUSDT"
        ]
        res = requests.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            timeout=8
        )
        # Binance逐个查
        results = []
        for sym in symbols:
            try:
                r = requests.get(
                    "https://fapi.binance.com/fapi/v1/openInterest?symbol=" + sym,
                    timeout=5
                )
                d = r.json()
                ticker_r = requests.get(
                    "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=" + sym,
                    timeout=5
                )
                t = ticker_r.json()
                oi = float(d.get("openInterest", 0))
                price = float(t.get("lastPrice", 0))
                oi_usd = oi * price
                change = float(t.get("priceChangePercent", 0))
                vol = float(t.get("quoteVolume", 0))
                results.append({
                    "symbol": sym.replace("USDT", ""),
                    "price": price,
                    "change": round(change, 2),
                    "oi": round(oi, 0),
                    "oi_usd": round(oi_usd),
                    "volume": round(vol),
                    "alert": abs(change) > 10 or vol > oi_usd * 2
                })
            except:
                continue
        results.sort(key=lambda x: abs(x["change"]), reverse=True)
        return results
    except:
        return []

# ─── 4. 巨鲸钱包监控 ──────────────────────────────────────
def get_wallet_balances():
    wallets = [
        {"name": "Binance Cold Wallet 1", "address": "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", "emoji": "🟡"},
        {"name": "MicroStrategy (Saylor)", "address": "1P5ZEDWTKTFGxQjZphgWPQUpe554WKDfHQ", "emoji": "📊"},
        {"name": "Bitfinex Cold Wallet", "address": "3D2oetdNuZUqQHPJmcMDDHYoqkyNVsFk9r", "emoji": "💹"},
        {"name": "Binance Hot Wallet", "address": "1NDyJtNTjmwk5xPNhjgAMu4HDHigtobu1s", "emoji": "🔥"},
        {"name": "Kraken Exchange", "address": "3FupZp77ySr7jwoLYEJ9mwzJpvoNBXsBnE", "emoji": "🐙"},
    ]
    btc_price = get_btc_price()
    result = []
    for w in wallets:
        try:
            r = requests.get(
                "https://blockchain.info/balance?active=" + w["address"],
                timeout=6
            )
            bal = r.json().get(w["address"], {}).get("final_balance", 0) / 1e8
            result.append({
                "name": w["name"],
                "address": w["address"][:14] + "...",
                "full_address": w["address"],
                "emoji": w["emoji"],
                "btc": round(bal, 2),
                "usd": round(bal * btc_price)
            })
        except:
            result.append({
                "name": w["name"],
                "address": w["address"][:14] + "...",
                "full_address": w["address"],
                "emoji": w["emoji"],
                "btc": None,
                "usd": None
            })
    return result

# ─── 5. SEC 13F 机构持仓 ───────────────────────────────────
def get_sec_holdings(cik):
    try:
        headers = {"User-Agent": "WhaleTracker admin@whaletracker.com"}
        cik_clean = str(int(cik))
        cik_padded = cik_clean.zfill(10)
        url = "https://data.sec.gov/submissions/CIK" + cik_padded + ".json"
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        latest_acc = None
        latest_date = None
        for i, form in enumerate(forms):
            if form == "13F-HR":
                latest_acc = accessions[i].replace("-", "")
                latest_date = dates[i]
                break
        if not latest_acc:
            return {"date": "N/A", "holdings": [], "total": 0, "error": "No 13F found"}
        idx_res = requests.get(
            "https://www.sec.gov/Archives/edgar/data/" + cik_clean + "/" + latest_acc + "/",
            headers=headers, timeout=10
        )
        infotable_match = re.search(r'href="([^"]*infotable[^"]*)"', idx_res.text, re.IGNORECASE)
        if not infotable_match:
            infotable_match = re.search(r'href="([^"]*Information[^"]*\.xml)"', idx_res.text, re.IGNORECASE)
        if infotable_match:
            infotable_name = infotable_match.group(1).split("/")[-1]
            h_url = "https://www.sec.gov/Archives/edgar/data/" + cik_clean + "/" + latest_acc + "/" + infotable_name
            h_res = requests.get(h_url, headers=headers, timeout=10)
            root = ET.fromstring(h_res.content)
            holdings = []
            total = 0
            for info in root.iter():
                if info.tag.endswith("infoTable"):
                    try:
                        name = ""
                        value = 0
                        shares = 0
                        for child in info:
                            tag = child.tag.split("}")[-1].lower()
                            if tag == "nameofissuer":
                                name = child.text or ""
                            elif tag == "value":
                                value = int(child.text or 0) * 1000
                            elif tag == "sshprnamt":
                                shares = int(child.text or 0)
                        if name and value > 0:
                            holdings.append({"name": name, "value": value, "shares": shares})
                            total += value
                    except:
                        continue
            holdings.sort(key=lambda x: x["value"], reverse=True)
            return {"date": latest_date, "holdings": holdings[:15], "total": total}
        return {"date": latest_date, "holdings": [], "total": 0, "error": "File not found"}
    except Exception as e:
        return {"date": "N/A", "holdings": [], "total": 0, "error": str(e)}

# ─── 6. 国会交易 ───────────────────────────────────────────
def get_congress_trades():
    try:
        res = requests.get(
            "https://house-stock-watcher-data.s3-us-gov-west-1.amazonaws.com/data/all_transactions.json",
            timeout=10
        )
        data = res.json()
        valid = [t for t in data if t.get("transaction_date") and t.get("ticker") and t.get("ticker") != "--"]
        recent = sorted(valid, key=lambda x: x.get("transaction_date", ""), reverse=True)[:25]
        result = []
        for t in recent:
            trade_type = t.get("type", "").lower()
            is_buy = "purchase" in trade_type
            result.append({
                "name": t.get("representative", "Unknown"),
                "ticker": t.get("ticker", "N/A").strip(),
                "type": "买入" if is_buy else "卖出",
                "is_buy": is_buy,
                "amount": t.get("amount", "N/A"),
                "date": t.get("transaction_date", ""),
                "asset": t.get("asset_description", "")[:50],
                "party": t.get("party", "")
            })
        return result
    except:
        return []

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Whale Tracker Pro</title>
<style>
:root {
  --bg: #f0f4ff;
  --surface: #ffffff;
  --surface2: #f8faff;
  --border: #e2e8f8;
  --accent: #6366f1;
  --accent2: #8b5cf6;
  --green: #059669;
  --green-bg: #ecfdf5;
  --red: #dc2626;
  --red-bg: #fef2f2;
  --orange: #ea580c;
  --orange-bg: #fff7ed;
  --yellow: #d97706;
  --yellow-bg: #fffbeb;
  --text: #0f172a;
  --text2: #334155;
  --muted: #64748b;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Inter", sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }

.header {
  background: rgba(255,255,255,0.97);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 0 24px; height: 60px;
  display: flex; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 100;
  box-shadow: 0 1px 12px rgba(99,102,241,0.06);
}
.logo { display: flex; align-items: center; gap: 10px; font-size: 18px; font-weight: 800; }
.logo-icon {
  width: 36px; height: 36px; border-radius: 10px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  display: flex; align-items: center; justify-content: center;
  color: white; font-size: 18px;
  box-shadow: 0 4px 12px rgba(99,102,241,0.3);
}
.logo span { background: linear-gradient(90deg, var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.header-right { display: flex; align-items: center; gap: 10px; }
.live-badge { display: flex; align-items: center; gap: 7px; background: var(--green-bg); border: 1px solid #a7f3d0; color: var(--green); padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 700; }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
.countdown { font-size: 12px; color: var(--muted); background: var(--surface2); border: 1px solid var(--border); padding: 6px 12px; border-radius: 20px; }
.refresh-btn { background: var(--accent); color: white; border: none; border-radius: 10px; padding: 8px 16px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; box-shadow: 0 4px 12px rgba(99,102,241,0.25); }
.refresh-btn:hover { transform: scale(1.03); }

.tabs { display: flex; background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 24px; overflow-x: auto; }
.tab { padding: 14px 18px; font-size: 13px; font-weight: 600; color: var(--muted); cursor: pointer; border: none; background: none; border-bottom: 2px solid transparent; white-space: nowrap; transition: all 0.2s; }
.tab:hover { color: var(--accent); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab .alert-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--red); margin-left: 5px; vertical-align: middle; animation: pulse 1s infinite; }

.content { max-width: 1400px; margin: 0 auto; padding: 20px 24px; }
.section-title { font-size: 18px; font-weight: 800; color: var(--text); margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
.section-sub { color: var(--muted); font-size: 12px; margin-bottom: 16px; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
.stat-card { background: var(--surface); border: 1.5px solid var(--border); border-radius: 14px; padding: 16px; box-shadow: 0 4px 16px rgba(99,102,241,0.05); }
.stat-label { font-size: 11px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.stat-value { font-size: 22px; font-weight: 900; color: var(--text); }
.stat-sub { font-size: 11px; color: var(--muted); margin-top: 4px; }

.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 16px; }
.card { background: var(--surface); border: 1.5px solid var(--border); border-radius: 16px; padding: 18px; box-shadow: 0 4px 24px rgba(99,102,241,0.06); margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.card-title { font-size: 14px; font-weight: 800; color: var(--text); display: flex; align-items: center; gap: 8px; }
.card-sub { color: var(--muted); font-size: 11px; margin-top: 3px; }

.badge { padding: 3px 9px; border-radius: 7px; font-size: 11px; font-weight: 700; }
.badge-purple { background: #f0f1ff; color: var(--accent); }
.badge-orange { background: var(--orange-bg); color: var(--orange); }
.badge-red { background: var(--red-bg); color: var(--red); }
.badge-green { background: var(--green-bg); color: var(--green); }
.badge-yellow { background: var(--yellow-bg); color: var(--yellow); }

.table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.table th { color: var(--muted); font-weight: 600; padding: 7px 10px; text-align: left; border-bottom: 1.5px solid var(--border); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
.table td { padding: 9px 10px; border-top: 1px solid var(--border); color: var(--text2); vertical-align: middle; }
.table tr:hover td { background: #f8faff; }
.table .alert-row td { background: #fff7ed !important; }

.alert-tag { display: inline-flex; align-items: center; gap: 4px; background: var(--red-bg); color: var(--red); padding: 2px 7px; border-radius: 6px; font-size: 10px; font-weight: 700; }
.up { color: var(--green); font-weight: 700; }
.down { color: var(--red); font-weight: 700; }
.mono { font-family: monospace; font-size: 11px; color: var(--muted); }

.filer-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 18px; }
.filer-card { background: var(--surface); border: 1.5px solid var(--border); border-radius: 12px; padding: 12px; cursor: pointer; transition: all 0.2s; }
.filer-card:hover, .filer-card.active { border-color: var(--accent); background: #f0f1ff; }
.filer-name { font-size: 12px; font-weight: 800; color: var(--text); margin-bottom: 3px; }
.filer-cik { font-size: 10px; color: var(--muted); }

.total-box { background: linear-gradient(135deg, #f0f1ff, #f5f3ff); border: 1px solid #e0e7ff; border-radius: 12px; padding: 12px 16px; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }
.total-label { font-size: 12px; color: var(--muted); font-weight: 600; }
.total-value { font-size: 20px; font-weight: 900; color: var(--accent); }

.loading { text-align: center; padding: 36px; color: var(--muted); font-size: 13px; }
.spinner { display: inline-block; width: 22px; height: 22px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 8px; }
@keyframes spin { to { transform: rotate(360deg); } }
.error-box { text-align: center; padding: 28px; color: var(--muted); font-size: 13px; background: var(--surface2); border-radius: 12px; border: 1px dashed var(--border); }
.hidden { display: none; }

.signal-card { border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; border: 1.5px solid; display: flex; align-items: center; justify-content: space-between; }
.signal-buy { background: var(--green-bg); border-color: #a7f3d0; }
.signal-sell { background: var(--red-bg); border-color: #fecaca; }
.signal-watch { background: var(--yellow-bg); border-color: #fde68a; }
.signal-title { font-size: 14px; font-weight: 800; }
.signal-desc { font-size: 12px; color: var(--muted); margin-top: 3px; }
.signal-time { font-size: 11px; color: var(--muted); }

.orange-pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--orange); box-shadow: 0 0 6px var(--orange); animation: pulse 1.5s infinite; display: inline-block; margin-right: 6px; }
</style>
</head>
<body>

<div class="header">
  <div class="logo">
    <div class="logo-icon">🐋</div>
    <span>Whale Tracker Pro</span>
  </div>
  <div class="header-right">
    <div class="countdown" id="countdown">刷新倒计时: 30s</div>
    <div class="live-badge"><div class="live-dot"></div>Auto Refresh</div>
    <button class="refresh-btn" onclick="refreshAll()">↻ 立即刷新</button>
  </div>
</div>

<div class="tabs">
  <button class="tab active" onclick="showTab('signals')">⚡ 跟庄信号<span class="alert-dot"></span></button>
  <button class="tab" onclick="showTab('volume')">📊 成交量异动</button>
  <button class="tab" onclick="showTab('oi')">📈 合约OI监控</button>
  <button class="tab" onclick="showTab('whale')">🐋 链上巨鲸</button>
  <button class="tab" onclick="showTab('wallets')">👛 巨鲸钱包</button>
  <button class="tab" onclick="showTab('institutions')">🏦 机构持仓</button>
  <button class="tab" onclick="showTab('congress')">🏛️ 国会交易</button>
</div>

<div class="content">

  <!-- 跟庄信号 -->
  <div id="tab-signals">
    <div class="section-title">⚡ 跟庄信号汇总</div>
    <div class="section-sub">综合链上巨鲸、成交量异动、合约OI变化，自动生成跟庄参考信号</div>
    <div class="stat-row">
      <div class="stat-card"><div class="stat-label">强烈买入信号</div><div class="stat-value" style="color:var(--green)" id="sig-buy">--</div><div class="stat-sub">综合评分≥80</div></div>
      <div class="stat-card"><div class="stat-label">观察信号</div><div class="stat-value" style="color:var(--yellow)" id="sig-watch">--</div><div class="stat-sub">综合评分50-80</div></div>
      <div class="stat-card"><div class="stat-label">卖出信号</div><div class="stat-value" style="color:var(--red)" id="sig-sell">--</div><div class="stat-sub">大资金出逃</div></div>
      <div class="stat-card"><div class="stat-label">BTC实时价格</div><div class="stat-value" id="sig-btc">--</div><div class="stat-sub">USD</div></div>
    </div>
    <div id="signalsList"><div class="loading"><div class="spinner"></div><br>生成跟庄信号...</div></div>
  </div>

  <!-- 成交量异动 -->
  <div id="tab-volume" class="hidden">
    <div class="section-title">📊 成交量异动监控</div>
    <div class="section-sub">成交量/市值比 &gt; 50% 且价格变动 &gt; 5% 视为异动，可能有大资金介入</div>
    <div id="volumeContent"><div class="loading"><div class="spinner"></div><br>加载中...</div></div>
  </div>

  <!-- 合约OI -->
  <div id="tab-oi" class="hidden">
    <div class="section-title">📈 合约未平仓量监控</div>
    <div class="section-sub">Binance U本位合约，OI突增代表大资金建仓，价格变动&gt;10%标记异动</div>
    <div id="oiContent"><div class="loading"><div class="spinner"></div><br>加载中...</div></div>
  </div>

  <!-- 链上巨鲸 -->
  <div id="tab-whale" class="hidden">
    <div class="section-title">🐋 链上巨鲸转账</div>
    <div class="section-sub">BTC链上单笔 ≥100 BTC 大额转账，500 BTC以上标记为超级巨鲸</div>
    <div class="stat-row">
      <div class="stat-card"><div class="stat-label">大额交易数</div><div class="stat-value" id="w-count">--</div><div class="stat-sub">≥100 BTC</div></div>
      <div class="stat-card"><div class="stat-label">最大单笔</div><div class="stat-value" id="w-max">--</div><div class="stat-sub">BTC</div></div>
      <div class="stat-card"><div class="stat-label">总转移量</div><div class="stat-value" id="w-total">--</div><div class="stat-sub">BTC</div></div>
      <div class="stat-card"><div class="stat-label">折合美元</div><div class="stat-value" id="w-usd">--</div><div class="stat-sub">USD</div></div>
    </div>
    <div class="card">
      <div id="whaleTable"><div class="loading"><div class="spinner"></div><br>加载中...</div></div>
    </div>
  </div>

  <!-- 巨鲸钱包 -->
  <div id="tab-wallets" class="hidden">
    <div class="section-title">👛 巨鲸钱包余额</div>
    <div class="section-sub">交易所和机构主要冷钱包实时余额监控</div>
    <div class="card">
      <div id="walletContent"><div class="loading"><div class="spinner"></div><br>查询链上余额...</div></div>
    </div>
  </div>

  <!-- 机构持仓 -->
  <div id="tab-institutions" class="hidden">
    <div class="section-title">🏦 机构持仓监控</div>
    <div class="section-sub">SEC EDGAR 13F季报，每季度更新</div>
    <div class="filer-grid" id="filerGrid"></div>
    <div id="holdingsContent"><div class="loading"><div class="spinner"></div><br>加载持仓数据...</div></div>
  </div>

  <!-- 国会交易 -->
  <div id="tab-congress" class="hidden">
    <div class="section-title">🏛️ 国会议员交易</div>
    <div class="section-sub">依据STOCK法案强制公开申报的股票交易记录</div>
    <div class="card">
      <div id="congressTable"><div class="loading"><div class="spinner"></div><br>加载中...</div></div>
    </div>
  </div>

</div>

<script>
var activeTab = 'signals';
var countdown = 30;
var timerInterval = null;
var activeFiler = 0;
var filers = [
  {name:"Berkshire Hathaway (Buffett)", cik:"0001067983", emoji:"🏦"},
  {name:"Bridgewater (Dalio)", cik:"0001350694", emoji:"🌉"},
  {name:"Soros Fund", cik:"0001029160", emoji:"💰"},
  {name:"Renaissance Tech", cik:"0001037389", emoji:"🔬"},
  {name:"Citadel Advisors", cik:"0001423298", emoji:"🏰"},
];

function showTab(tab) {
  activeTab = tab;
  var tabs = ['signals','volume','oi','whale','wallets','institutions','congress'];
  tabs.forEach(function(t) {
    document.getElementById('tab-'+t).classList.toggle('hidden', t !== tab);
  });
  document.querySelectorAll('.tab').forEach(function(el, i) {
    el.classList.toggle('active', tabs[i] === tab);
  });
  loadTab(tab);
}

function loadTab(tab) {
  if (tab === 'signals') loadSignals();
  else if (tab === 'volume') loadVolume();
  else if (tab === 'oi') loadOI();
  else if (tab === 'whale') loadWhale();
  else if (tab === 'wallets') loadWallets();
  else if (tab === 'institutions') { renderFilerGrid(); loadHoldings(filers[0].cik, filers[0].name); }
  else if (tab === 'congress') loadCongress();
}

function startCountdown() {
  clearInterval(timerInterval);
  countdown = 30;
  timerInterval = setInterval(function() {
    countdown--;
    document.getElementById('countdown').textContent = '刷新倒计时: ' + countdown + 's';
    if (countdown <= 0) {
      countdown = 30;
      loadTab(activeTab);
    }
  }, 1000);
}

function refreshAll() {
  countdown = 30;
  loadTab(activeTab);
}

// ── 跟庄信号 ──────────────────────────────
function loadSignals() {
  Promise.all([
    fetch('/volume_alerts').then(function(r){return r.json();}).catch(function(){return[];}),
    fetch('/oi_alerts').then(function(r){return r.json();}).catch(function(){return[];}),
    fetch('/btc_price').then(function(r){return r.json();}).catch(function(){return{price:75000};})
  ]).then(function(results) {
    var volAlerts = results[0];
    var oiAlerts = results[1];
    var btcPrice = results[2].price;

    document.getElementById('sig-btc').textContent = '$' + btcPrice.toLocaleString();

    var signals = [];

    // 从成交量异动生成信号
    volAlerts.forEach(function(v) {
      if (Math.abs(v.change) > 10) {
        var isBuy = v.change > 0;
        signals.push({
          symbol: v.symbol,
          type: isBuy ? 'buy' : 'sell',
          score: Math.min(95, Math.round(Math.abs(v.change) * 2 + v.vol_mcap_ratio * 20)),
          reason: '成交量异动 ' + v.vol_mcap_ratio + 'x | 价格' + (isBuy?'上涨':'下跌') + ' ' + Math.abs(v.change) + '%',
          price: v.price,
          change: v.change
        });
      }
    });

    // 从OI异动生成信号
    oiAlerts.forEach(function(o) {
      if (Math.abs(o.change) > 10) {
        var isBuy = o.change > 0;
        signals.push({
          symbol: o.symbol,
          type: isBuy ? 'buy' : 'watch',
          score: Math.min(90, Math.round(Math.abs(o.change) * 1.5 + 30)),
          reason: '合约OI异动 | 价格' + (isBuy?'上涨':'下跌') + ' ' + Math.abs(o.change) + '%',
          price: o.price,
          change: o.change
        });
      }
    });

    signals.sort(function(a,b){return b.score - a.score;});

    var buyCount = signals.filter(function(s){return s.type==='buy' && s.score>=80;}).length;
    var watchCount = signals.filter(function(s){return s.type==='watch' || s.score<80;}).length;
    var sellCount = signals.filter(function(s){return s.type==='sell';}).length;

    document.getElementById('sig-buy').textContent = buyCount;
    document.getElementById('sig-watch').textContent = watchCount;
    document.getElementById('sig-sell').textContent = sellCount;

    if (!signals.length) {
      document.getElementById('signalsList').innerHTML = '<div class="error-box">暂无明显异动信号，市场平静</div>';
      return;
    }

    var html = '';
    signals.slice(0,20).forEach(function(s) {
      var cls = s.type === 'buy' ? 'signal-buy' : s.type === 'sell' ? 'signal-sell' : 'signal-watch';
      var icon = s.type === 'buy' ? '🟢' : s.type === 'sell' ? '🔴' : '🟡';
      var label = s.type === 'buy' ? '买入信号' : s.type === 'sell' ? '卖出信号' : '观察信号';
      html += '<div class="signal-card ' + cls + '">' +
        '<div>' +
          '<div class="signal-title">' + icon + ' ' + s.symbol + ' — ' + label + ' (评分: ' + s.score + ')</div>' +
          '<div class="signal-desc">' + s.reason + '</div>' +
        '</div>' +
        '<div style="text-align:right">' +
          '<div style="font-weight:800;font-size:15px">$' + (s.price||0).toLocaleString('en-US',{maximumFractionDigits:6}) + '</div>' +
          '<div class="' + (s.change>=0?'up':'down') + '" style="font-size:12px">' + (s.change>=0?'+':'') + s.change + '%</div>' +
        '</div>' +
        '</div>';
    });

    html += '<div style="color:var(--muted);font-size:11px;margin-top:16px;padding:12px;background:var(--yellow-bg);border-radius:10px;border:1px solid #fde68a;">⚠️ 免责声明：本工具仅供参考，不构成投资建议。加密货币投资风险极高，请勿全仓操作。</div>';
    document.getElementById('signalsList').innerHTML = html;
  });
}

// ── 成交量异动 ─────────────────────────────
function loadVolume() {
  document.getElementById('volumeContent').innerHTML = '<div class="loading"><div class="spinner"></div><br>加载中...</div>';
  fetch('/volume_alerts').then(function(r){return r.json();}).then(function(data) {
    if (!data || !data.length) {
      document.getElementById('volumeContent').innerHTML = '<div class="error-box">暂无异动数据</div>';
      return;
    }
    var html = '<div class="card"><table class="table">' +
      '<tr><th>币种</th><th>当前价格</th><th>24h涨跌</th><th>成交量</th><th>量/市值</th><th>状态</th></tr>';
    data.forEach(function(v) {
      var isAlert = v.alert;
      html += '<tr class="' + (isAlert?'alert-row':'') + '">' +
        '<td><div style="font-weight:800">' + v.symbol + '</div><div style="color:var(--muted);font-size:11px">' + v.name + '</div></td>' +
        '<td style="font-weight:700">$' + (v.price||0).toLocaleString('en-US',{maximumFractionDigits:6}) + '</td>' +
        '<td class="' + (v.change>=0?'up':'down') + '">' + (v.change>=0?'+':'') + v.change + '%</td>' +
        '<td style="color:var(--muted)">$' + (v.volume/1e6).toFixed(1) + 'M</td>' +
        '<td style="font-weight:700;color:var(--orange)">' + v.vol_mcap_ratio + 'x</td>' +
        '<td>' + (isAlert ? '<span class="alert-tag">🔥 强异动</span>' : '<span class="badge badge-yellow">异动</span>') + '</td>' +
        '</tr>';
    });
    html += '</table></div>';
    document.getElementById('volumeContent').innerHTML = html;
  }).catch(function() {
    document.getElementById('volumeContent').innerHTML = '<div class="error-box">网络错误，请重试</div>';
  });
}

// ── 合约OI ─────────────────────────────────
function loadOI() {
  document.getElementById('oiContent').innerHTML = '<div class="loading"><div class="spinner"></div><br>加载中...</div>';
  fetch('/oi_alerts').then(function(r){return r.json();}).then(function(data) {
    if (!data || !data.length) {
      document.getElementById('oiContent').innerHTML = '<div class="error-box">暂无数据</div>';
      return;
    }
    var html = '<div class="card"><table class="table">' +
      '<tr><th>合约</th><th>价格</th><th>24h涨跌</th><th>未平仓量(OI)</th><th>OI美元值</th><th>成交量</th><th>状态</th></tr>';
    data.forEach(function(o) {
      html += '<tr class="' + (o.alert?'alert-row':'') + '">' +
        '<td style="font-weight:800">' + o.symbol + '/USDT</td>' +
        '<td style="font-weight:700">$' + o.price.toLocaleString('en-US',{maximumFractionDigits:4}) + '</td>' +
        '<td class="' + (o.change>=0?'up':'down') + '">' + (o.change>=0?'+':'') + o.change + '%</td>' +
        '<td style="color:var(--muted)">' + o.oi.toLocaleString() + '</td>' +
        '<td style="font-weight:700;color:var(--accent)">$' + (o.oi_usd/1e6).toFixed(1) + 'M</td>' +
        '<td style="color:var(--muted)">$' + (o.volume/1e6).toFixed(1) + 'M</td>' +
        '<td>' + (o.alert ? '<span class="alert-tag">⚡ 异动</span>' : '<span class="badge badge-purple">正常</span>') + '</td>' +
        '</tr>';
    });
    html += '</table></div>';
    document.getElementById('oiContent').innerHTML = html;
  }).catch(function() {
    document.getElementById('oiContent').innerHTML = '<div class="error-box">网络错误，请重试</div>';
  });
}

// ── 链上巨鲸 ───────────────────────────────
function loadWhale() {
  fetch('/whale_txns').then(function(r){return r.json();}).then(function(data) {
    if (!data || !data.length) {
      document.getElementById('whaleTable').innerHTML = '<div class="error-box">暂无大额交易</div>';
      return;
    }
    var total = data.reduce(function(s,t){return s+t.btc;},0);
    var totalUsd = data.reduce(function(s,t){return s+t.usd;},0);
    var max = Math.max.apply(null, data.map(function(t){return t.btc;}));
    document.getElementById('w-count').textContent = data.length;
    document.getElementById('w-max').textContent = max.toFixed(1);
    document.getElementById('w-total').textContent = total.toFixed(1);
    document.getElementById('w-usd').textContent = '$' + (totalUsd/1e6).toFixed(1) + 'M';
    var html = '<table class="table"><tr><th>交易Hash</th><th>BTC金额</th><th>USD价值</th><th>手续费</th><th>状态</th></tr>';
    data.forEach(function(t) {
      html += '<tr class="' + (t.alert?'alert-row':'') + '">' +
        '<td class="mono">' + t.hash + '</td>' +
        '<td style="font-weight:800;color:' + (t.alert?'var(--orange)':'var(--text)') + '">' + t.btc.toLocaleString() + ' BTC</td>' +
        '<td style="color:var(--muted)">$' + t.usd.toLocaleString() + '</td>' +
        '<td style="color:var(--muted)">' + t.fee + ' BTC</td>' +
        '<td>' + (t.alert ? '<span class="alert-tag">🐋 超级巨鲸</span>' : '<span class="badge badge-purple">大额</span>') + '</td>' +
        '</tr>';
    });
    html += '</table>';
    document.getElementById('whaleTable').innerHTML = html;
  }).catch(function() {
    document.getElementById('whaleTable').innerHTML = '<div class="error-box">网络错误</div>';
  });
}

// ── 巨鲸钱包 ───────────────────────────────
function loadWallets() {
  fetch('/wallet_balances').then(function(r){return r.json();}).then(function(data) {
    var html = '<table class="table"><tr><th>钱包名称</th><th>地址</th><th>BTC余额</th><th>USD价值</th><th>链接</th></tr>';
    data.forEach(function(w) {
      html += '<tr>' +
        '<td style="font-weight:700">' + w.emoji + ' ' + w.name + '</td>' +
        '<td class="mono">' + w.address + '</td>' +
        '<td style="font-weight:800;color:var(--orange)">' + (w.btc !== null ? w.btc.toLocaleString() + ' BTC' : '查询失败') + '</td>' +
        '<td style="color:var(--muted)">' + (w.usd !== null ? '$' + w.usd.toLocaleString() : '--') + '</td>' +
        '<td><a href="https://www.blockchain.com/btc/address/' + w.full_address + '" target="_blank" style="color:var(--accent);font-size:12px">查看 ↗</a></td>' +
        '</tr>';
    });
    html += '</table>';
    document.getElementById('walletContent').innerHTML = html;
  }).catch(function() {
    document.getElementById('walletContent').innerHTML = '<div class="error-box">网络错误</div>';
  });
}

// ── 机构持仓 ───────────────────────────────
function renderFilerGrid() {
  var grid = document.getElementById('filerGrid');
  grid.innerHTML = filers.map(function(f, i) {
    return '<div class="filer-card' + (i===activeFiler?' active':'') + '" onclick="selectFiler(' + i + ')">' +
      '<div class="filer-name">' + f.emoji + ' ' + f.name + '</div>' +
      '<div class="filer-cik">CIK: ' + f.cik + '</div></div>';
  }).join('');
}

function selectFiler(idx) {
  activeFiler = idx;
  renderFilerGrid();
  loadHoldings(filers[idx].cik, filers[idx].name);
}

function loadHoldings(cik, name) {
  document.getElementById('holdingsContent').innerHTML = '<div class="loading"><div class="spinner"></div><br>从SEC EDGAR获取数据...</div>';
  fetch('/sec_holdings?cik=' + encodeURIComponent(cik))
    .then(function(r){return r.json();})
    .then(function(data) {
      if (!data || !data.holdings || !data.holdings.length) {
        document.getElementById('holdingsContent').innerHTML = '<div class="error-box">⚠️ ' + (data.error||'暂无数据，请稍后重试') + '</div>';
        return;
      }
      var total = data.total ? '$' + (data.total/1e9).toFixed(2) + 'B' : 'N/A';
      var html = '<div class="card">' +
        '<div class="card-header"><div><div class="card-title">' + name + ' 持仓明细</div><div class="card-sub">报告日期：' + data.date + '</div></div><span class="badge badge-purple">13F-HR</span></div>' +
        '<div class="total-box"><div class="total-label">总持仓市值</div><div class="total-value">' + total + '</div></div>' +
        '<table class="table"><tr><th>#</th><th>股票名称</th><th>持仓市值</th><th>持仓份额</th></tr>';
      data.holdings.forEach(function(h, i) {
        html += '<tr><td style="color:var(--muted)">' + (i+1) + '</td><td style="font-weight:700">' + h.name + '</td><td style="font-weight:700;color:var(--accent)">$' + (h.value/1e6).toFixed(1) + 'M</td><td style="color:var(--muted)">' + h.shares.toLocaleString() + '</td></tr>';
      });
      html += '</table></div>';
      document.getElementById('holdingsContent').innerHTML = html;
    })
    .catch(function() {
      document.getElementById('holdingsContent').innerHTML = '<div class="error-box">网络错误</div>';
    });
}

// ── 国会交易 ───────────────────────────────
function loadCongress() {
  fetch('/congress_trades').then(function(r){return r.json();}).then(function(data) {
    if (!data || !data.length) {
      document.getElementById('congressTable').innerHTML = '<div class="error-box">暂无数据</div>';
      return;
    }
    var html = '<table class="table"><tr><th>议员</th><th>政党</th><th>股票代码</th><th>资产名称</th><th>操作</th><th>金额</th><th>日期</th></tr>';
    data.forEach(function(t) {
      html += '<tr>' +
        '<td style="font-weight:700">' + t.name + '</td>' +
        '<td style="color:var(--muted);font-size:11px">' + (t.party||'') + '</td>' +
        '<td style="font-weight:800;color:var(--accent)">' + t.ticker + '</td>' +
        '<td style="color:var(--muted);font-size:11px">' + (t.asset||'') + '</td>' +
        '<td><span class="' + (t.is_buy?'up':'down') + '">' + t.type + '</span></td>' +
        '<td style="font-weight:600">' + t.amount + '</td>' +
        '<td style="color:var(--muted);font-size:11px">' + t.date + '</td>' +
        '</tr>';
    });
    html += '</table>';
    document.getElementById('congressTable').innerHTML = html;
  }).catch(function() {
    document.getElementById('congressTable').innerHTML = '<div class="error-box">网络错误</div>';
  });
}

loadSignals();
startCountdown();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/btc_price")
def btc_price():
    return jsonify({"price": get_btc_price()})

@app.route("/volume_alerts")
def volume_alerts():
    return jsonify(get_volume_alerts())

@app.route("/oi_alerts")
def oi_alerts():
    return jsonify(get_oi_alerts())

@app.route("/whale_txns")
def whale_txns():
    return jsonify(get_whale_txns())

@app.route("/wallet_balances")
def wallet_balances():
    return jsonify(get_wallet_balances())

@app.route("/sec_holdings")
def sec_holdings():
    cik = request.args.get("cik", "0001067983")
    return jsonify(get_sec_holdings(cik))

@app.route("/congress_trades")
def congress_trades():
    return jsonify(get_congress_trades())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
