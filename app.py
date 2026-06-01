from flask import Flask, request, jsonify, render_template_string
import requests
import os
import datetime

app = Flask(__name__)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

# 知名机构SEC CIK号码
SEC_FILERS = [
    {"name": "Berkshire Hathaway (Buffett)", "cik": "0001067983", "emoji": "🏦"},
    {"name": "Bridgewater Associates (Dalio)", "cik": "0001350694", "emoji": "🌉"},
    {"name": "Soros Fund Management", "cik": "0001029160", "emoji": "💰"},
    {"name": "Renaissance Technologies", "cik": "0001037389", "emoji": "🔬"},
    {"name": "Citadel Advisors", "cik": "0001423298", "emoji": "🏰"},
]

# 知名加密巨鲸钱包地址
WHALE_WALLETS = [
    {"name": "Binance Cold Wallet", "address": "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", "chain": "BTC", "emoji": "🟡"},
    {"name": "MicroStrategy (Saylor)", "address": "1P5ZEDWTKTFGxQjZphgWPQUpe554WKDfHQ", "chain": "BTC", "emoji": "📊"},
    {"name": "Bitfinex Cold Wallet", "address": "3D2oetdNuZUqQHPJmcMDDHYoqkyNVsFk9r", "chain": "BTC", "emoji": "💹"},
    {"name": "Huobi Exchange", "address": "1HckjUpRGcrrRAtFaaCAUaGjsPx9oYmLaZ", "chain": "BTC", "emoji": "🔥"},
]

def get_sec_holdings(cik):
    try:
        headers = {"User-Agent": "WhaleTracker research@example.com"}
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        res = requests.get(url, headers=headers, timeout=8)
        data = res.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        filings_13f = []
        for i, form in enumerate(forms):
            if form == "13F-HR":
                filings_13f.append({
                    "date": dates[i],
                    "accession": accessions[i].replace("-", "")
                })
                if len(filings_13f) >= 1:
                    break
        if not filings_13f:
            return None
        latest = filings_13f[0]
        acc = latest["accession"]
        index_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{acc}-index.json"
        idx_res = requests.get(index_url, headers=headers, timeout=8)
        idx_data = idx_res.json()
        holdings_file = None
        for item in idx_data.get("directory", {}).get("item", []):
            if "infotable" in item.get("name", "").lower():
                holdings_file = item["name"]
                break
        if not holdings_file:
            return {"date": latest["date"], "holdings": [], "total": 0}
        holdings_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{holdings_file}"
        h_res = requests.get(holdings_url, headers=headers, timeout=8)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(h_res.content)
        ns = {"ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}
        holdings = []
        total = 0
        for info in root.findall(".//ns:infoTable", ns) or root.findall(".//{*}infoTable"):
            try:
                name = (info.find("{*}nameOfIssuer") or info.find("ns:nameOfIssuer", ns)).text
                value = int((info.find("{*}value") or info.find("ns:value", ns)).text) * 1000
                shares_el = info.find("{*}sshPrnamt") or info.find("ns:sshPrnamt", ns)
                shares = int(shares_el.text) if shares_el is not None else 0
                holdings.append({"name": name, "value": value, "shares": shares})
                total += value
            except:
                continue
        holdings.sort(key=lambda x: x["value"], reverse=True)
        return {"date": latest["date"], "holdings": holdings[:15], "total": total}
    except Exception as e:
        return None

def get_btc_whale_txns():
    try:
        res = requests.get(
            "https://blockchain.info/unconfirmed-transactions?format=json&limit=50",
            timeout=8
        )
        txns = res.json().get("txs", [])
        big_txns = []
        for tx in txns:
            out_value = sum(o.get("value", 0) for o in tx.get("out", [])) / 1e8
            if out_value >= 10:
                big_txns.append({
                    "hash": tx["hash"][:16] + "...",
                    "value_btc": round(out_value, 2),
                    "value_usd": 0,
                    "time": "pending",
                    "inputs": len(tx.get("inputs", [])),
                    "outputs": len(tx.get("out", []))
                })
        big_txns.sort(key=lambda x: x["value_btc"], reverse=True)
        btc_price = get_btc_price()
        for t in big_txns:
            t["value_usd"] = round(t["value_btc"] * btc_price)
        return big_txns[:20]
    except:
        return []

def get_btc_price():
    try:
        res = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            timeout=5
        )
        return res.json()["bitcoin"]["usd"]
    except:
        return 75000

def get_congress_trades():
    try:
        res = requests.get(
            "https://house-stock-watcher-data.s3-us-gov-west-1.amazonaws.com/data/all_transactions.json",
            timeout=8
        )
        data = res.json()
        recent = sorted(data, key=lambda x: x.get("transaction_date", ""), reverse=True)[:20]
        result = []
        for t in recent:
            result.append({
                "name": t.get("representative", "Unknown"),
                "ticker": t.get("ticker", "N/A"),
                "type": t.get("type", ""),
                "amount": t.get("amount", ""),
                "date": t.get("transaction_date", ""),
                "asset": t.get("asset_description", "")
            })
        return result
    except:
        return []

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Whale Tracker</title>
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
  --text: #0f172a;
  --text2: #334155;
  --muted: #64748b;
  --orange: #ea580c;
  --orange-bg: #fff7ed;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Inter", sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }

.header {
  background: rgba(255,255,255,0.97);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  height: 60px;
  display: flex; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 100;
  box-shadow: 0 1px 12px rgba(99,102,241,0.06);
}
.logo { display: flex; align-items: center; gap: 10px; font-size: 18px; font-weight: 800; }
.logo-icon {
  width: 36px; height: 36px; border-radius: 10px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  display: flex; align-items: center; justify-content: center;
  color: white; font-size: 16px;
  box-shadow: 0 4px 12px rgba(99,102,241,0.3);
}
.logo span { background: linear-gradient(90deg, var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.header-right { display: flex; align-items: center; gap: 12px; }
.live-badge {
  display: flex; align-items: center; gap: 7px;
  background: var(--green-bg); border: 1px solid #a7f3d0;
  color: var(--green); padding: 6px 14px; border-radius: 20px;
  font-size: 12px; font-weight: 700;
}
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
.refresh-btn {
  background: var(--accent); color: white; border: none;
  border-radius: 10px; padding: 8px 16px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: all 0.2s;
  box-shadow: 0 4px 12px rgba(99,102,241,0.25);
}
.refresh-btn:hover { transform: scale(1.03); }

.tabs {
  display: flex; gap: 0;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  overflow-x: auto;
}
.tab {
  padding: 14px 20px; font-size: 13px; font-weight: 600;
  color: var(--muted); cursor: pointer; border: none; background: none;
  border-bottom: 2px solid transparent; white-space: nowrap;
  transition: all 0.2s;
}
.tab:hover { color: var(--accent); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }

.content { max-width: 1400px; margin: 0 auto; padding: 24px; }

.section-title {
  font-size: 20px; font-weight: 800; color: var(--text);
  margin-bottom: 6px; display: flex; align-items: center; gap: 10px;
}
.section-sub { color: var(--muted); font-size: 13px; margin-bottom: 20px; }

.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(580px, 1fr)); gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 16px; }

.card {
  background: var(--surface); border: 1.5px solid var(--border);
  border-radius: 16px; padding: 20px;
  box-shadow: 0 4px 24px rgba(99,102,241,0.06);
}
.card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.card-title { font-size: 15px; font-weight: 800; color: var(--text); display: flex; align-items: center; gap: 8px; }
.card-sub { color: var(--muted); font-size: 11px; margin-top: 3px; }
.card-badge { padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: 700; }
.badge-purple { background: #f0f1ff; color: var(--accent); }
.badge-green { background: var(--green-bg); color: var(--green); }
.badge-orange { background: var(--orange-bg); color: var(--orange); }
.badge-red { background: var(--red-bg); color: var(--red); }

.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th { color: var(--muted); font-weight: 600; padding: 8px 10px; text-align: left; border-bottom: 1.5px solid var(--border); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
.table th:last-child { text-align: right; }
.table td { padding: 10px 10px; border-top: 1px solid var(--border); color: var(--text2); vertical-align: middle; }
.table td:last-child { text-align: right; }
.table tr:hover td { background: #f8faff; }

.holding-name { font-weight: 700; color: var(--text); font-size: 13px; }
.holding-val { font-weight: 700; color: var(--accent); }

.whale-amount { font-weight: 800; font-size: 14px; }
.whale-usd { color: var(--muted); font-size: 11px; }
.whale-hash { font-family: monospace; font-size: 11px; color: var(--muted); }

.congress-buy { color: var(--green); font-weight: 700; }
.congress-sell { color: var(--red); font-weight: 700; }

.total-box {
  background: linear-gradient(135deg, #f0f1ff, #f5f3ff);
  border: 1px solid #e0e7ff; border-radius: 12px;
  padding: 14px 16px; margin-bottom: 16px;
  display: flex; justify-content: space-between; align-items: center;
}
.total-label { font-size: 12px; color: var(--muted); font-weight: 600; }
.total-value { font-size: 20px; font-weight: 900; color: var(--accent); }

.loading { text-align: center; padding: 40px; color: var(--muted); font-size: 14px; }
.loading-spinner { display: inline-block; width: 24px; height: 24px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 10px; }
@keyframes spin { to { transform: rotate(360deg); } }

.error-box { text-align: center; padding: 30px; color: var(--muted); font-size: 13px; background: var(--surface2); border-radius: 12px; border: 1px dashed var(--border); }

.filer-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-bottom: 20px; }
.filer-card {
  background: var(--surface2); border: 1.5px solid var(--border);
  border-radius: 12px; padding: 14px; cursor: pointer; transition: all 0.2s;
}
.filer-card:hover, .filer-card.active { border-color: var(--accent); background: #f0f1ff; }
.filer-name { font-size: 13px; font-weight: 800; color: var(--text); margin-bottom: 4px; }
.filer-cik { font-size: 11px; color: var(--muted); }

.whale-live { display: flex; align-items: center; gap: 6px; }
.whale-live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--orange); box-shadow: 0 0 6px var(--orange); animation: pulse 1.5s infinite; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
.stat-card {
  background: var(--surface); border: 1.5px solid var(--border);
  border-radius: 14px; padding: 16px;
  box-shadow: 0 4px 16px rgba(99,102,241,0.05);
}
.stat-label { font-size: 11px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.stat-value { font-size: 22px; font-weight: 900; color: var(--text); }
.stat-sub { font-size: 11px; color: var(--muted); margin-top: 4px; }

.hidden { display: none; }
</style>
</head>
<body>

<div class="header">
  <div class="logo">
    <div class="logo-icon">🐋</div>
    <span>Whale Tracker</span>
  </div>
  <div class="header-right">
    <div class="live-badge"><div class="live-dot"></div>Live Monitoring</div>
    <button class="refresh-btn" onclick="refreshAll()">↻ Refresh</button>
  </div>
</div>

<div class="tabs">
  <button class="tab active" onclick="showTab('institutions')">🏦 机构持仓</button>
  <button class="tab" onclick="showTab('whales')">🐋 加密巨鲸</button>
  <button class="tab" onclick="showTab('congress')">🏛️ 国会交易</button>
</div>

<div class="content">

  <!-- 机构持仓 -->
  <div id="tab-institutions">
    <div class="section-title">🏦 机构持仓监控</div>
    <div class="section-sub">数据来源：SEC EDGAR 13F季报，每季度更新一次</div>

    <div class="filer-grid" id="filerGrid"></div>

    <div id="holdingsContent">
      <div class="loading"><div class="loading-spinner"></div><br>加载持仓数据...</div>
    </div>
  </div>

  <!-- 加密巨鲸 -->
  <div id="tab-whales" class="hidden">
    <div class="section-title">🐋 加密巨鲸实时监控</div>
    <div class="section-sub">实时监控BTC链上大额交易（≥10 BTC），数据来源：Blockchain.info</div>

    <div class="stat-row" id="whaleStats">
      <div class="stat-card"><div class="stat-label">监控交易数</div><div class="stat-value" id="stat-txns">--</div><div class="stat-sub">≥10 BTC</div></div>
      <div class="stat-card"><div class="stat-label">最大单笔</div><div class="stat-value" id="stat-max">--</div><div class="stat-sub">BTC</div></div>
      <div class="stat-card"><div class="stat-label">总转移量</div><div class="stat-value" id="stat-total">--</div><div class="stat-sub">BTC</div></div>
      <div class="stat-card"><div class="stat-label">折合美元</div><div class="stat-value" id="stat-usd">--</div><div class="stat-sub">USD</div></div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">
              <div class="whale-live"><div class="whale-live-dot"></div>实时大额交易</div>
            </div>
            <div class="card-sub">BTC链上未确认 ≥10 BTC 交易</div>
          </div>
          <span class="card-badge badge-orange">LIVE</span>
        </div>
        <div id="whaleTable"><div class="loading"><div class="loading-spinner"></div><br>加载中...</div></div>
      </div>

      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">📍 知名钱包监控</div>
            <div class="card-sub">交易所和机构主要冷钱包</div>
          </div>
          <span class="card-badge badge-purple">WATCH</span>
        </div>
        <div id="walletTable"><div class="loading"><div class="loading-spinner"></div><br>加载中...</div></div>
      </div>
    </div>
  </div>

  <!-- 国会交易 -->
  <div id="tab-congress" class="hidden">
    <div class="section-title">🏛️ 美国国会议员交易记录</div>
    <div class="section-sub">数据来源：House Stock Watcher，依据STOCK法案公开申报</div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">最新申报交易</div>
          <div class="card-sub">国会议员最近股票交易记录</div>
        </div>
        <span class="card-badge badge-purple">PUBLIC DATA</span>
      </div>
      <div id="congressTable"><div class="loading"><div class="loading-spinner"></div><br>加载中...</div></div>
    </div>
  </div>

</div>

<script>
var filers = [
  {name:"Berkshire Hathaway (Buffett)", cik:"0001067983", emoji:"🏦"},
  {name:"Bridgewater Associates (Dalio)", cik:"0001350694", emoji:"🌉"},
  {name:"Soros Fund Management", cik:"0001029160", emoji:"💰"},
  {name:"Renaissance Technologies", cik:"0001037389", emoji:"🔬"},
  {name:"Citadel Advisors", cik:"0001423298", emoji:"🏰"},
];
var activeFiler = 0;
var activeTab = 'institutions';

function showTab(tab) {
  activeTab = tab;
  ['institutions','whales','congress'].forEach(function(t) {
    document.getElementById('tab-'+t).classList.toggle('hidden', t !== tab);
  });
  document.querySelectorAll('.tab').forEach(function(el, i) {
    el.classList.toggle('active', ['institutions','whales','congress'][i] === tab);
  });
  if (tab === 'whales') loadWhales();
  if (tab === 'congress') loadCongress();
}

function renderFilerGrid() {
  var grid = document.getElementById('filerGrid');
  grid.innerHTML = filers.map(function(f, i) {
    return '<div class="filer-card' + (i === activeFiler ? ' active' : '') + '" onclick="selectFiler(' + i + ')">' +
      '<div class="filer-name">' + f.emoji + ' ' + f.name + '</div>' +
      '<div class="filer-cik">CIK: ' + f.cik + '</div>' +
      '</div>';
  }).join('');
}

function selectFiler(idx) {
  activeFiler = idx;
  renderFilerGrid();
  loadHoldings(filers[idx].cik, filers[idx].name);
}

function loadHoldings(cik, name) {
  var box = document.getElementById('holdingsContent');
  box.innerHTML = '<div class="loading"><div class="loading-spinner"></div><br>从SEC EDGAR获取数据...</div>';
  fetch('/sec_holdings?cik=' + encodeURIComponent(cik))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data || !data.holdings || !data.holdings.length) {
        box.innerHTML = '<div class="error-box">暂无数据或API限制，请稍后重试</div>';
        return;
      }
      var total = data.total ? '$' + (data.total/1e9).toFixed(2) + 'B' : 'N/A';
      var html = '<div class="card">' +
        '<div class="card-header"><div><div class="card-title">' + name + ' 持仓明细</div><div class="card-sub">报告日期：' + data.date + '</div></div><span class="card-badge badge-purple">13F-HR</span></div>' +
        '<div class="total-box"><div class="total-label">总持仓市值</div><div class="total-value">' + total + '</div></div>' +
        '<table class="table"><tr><th>#</th><th>股票名称</th><th>持仓市值</th><th>持仓份额</th></tr>';
      data.holdings.forEach(function(h, i) {
        html += '<tr><td style="color:var(--muted);font-size:12px">' + (i+1) + '</td>' +
          '<td class="holding-name">' + h.name + '</td>' +
          '<td class="holding-val">$' + (h.value/1e6).toFixed(1) + 'M</td>' +
          '<td style="color:var(--muted)">' + h.shares.toLocaleString() + '</td></tr>';
      });
      html += '</table></div>';
      box.innerHTML = html;
    })
    .catch(function() {
      box.innerHTML = '<div class="error-box">网络错误，请重试</div>';
    });
}

function loadWhales() {
  fetch('/whale_txns')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data || !data.length) {
        document.getElementById('whaleTable').innerHTML = '<div class="error-box">暂无大额交易数据</div>';
        return;
      }
      var totalBtc = data.reduce(function(s,t){return s+t.value_btc;},0);
      var totalUsd = data.reduce(function(s,t){return s+t.value_usd;},0);
      var maxBtc = Math.max.apply(null, data.map(function(t){return t.value_btc;}));
      document.getElementById('stat-txns').textContent = data.length;
      document.getElementById('stat-max').textContent = maxBtc.toFixed(1);
      document.getElementById('stat-total').textContent = totalBtc.toFixed(1);
      document.getElementById('stat-usd').textContent = '$' + (totalUsd/1e6).toFixed(1) + 'M';
      var html = '<table class="table"><tr><th>交易Hash</th><th>BTC金额</th><th>USD价值</th><th>输入/输出</th></tr>';
      data.forEach(function(t) {
        var big = t.value_btc >= 100;
        html += '<tr>' +
          '<td class="whale-hash">' + t.hash + '</td>' +
          '<td class="whale-amount" style="color:' + (big?'var(--orange)':'var(--text)') + '">' + t.value_btc.toLocaleString() + ' BTC</td>' +
          '<td style="color:var(--muted);font-size:12px">$' + t.value_usd.toLocaleString() + '</td>' +
          '<td style="color:var(--muted);font-size:12px">' + t.inputs + '→' + t.outputs + '</td>' +
          '</tr>';
      });
      html += '</table>';
      document.getElementById('whaleTable').innerHTML = html;
    })
    .catch(function() {
      document.getElementById('whaleTable').innerHTML = '<div class="error-box">网络错误，请重试</div>';
    });

  var wallets = [
    {name:"Binance Cold Wallet", address:"34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", emoji:"🟡"},
    {name:"MicroStrategy (Saylor)", address:"1P5ZEDWTKTFGxQjZphgWPQUpe554WKDfHQ", emoji:"📊"},
    {name:"Bitfinex Cold Wallet", address:"3D2oetdNuZUqQHPJmcMDDHYoqkyNVsFk9r", emoji:"💹"},
  ];
  var html = '<table class="table"><tr><th>钱包名称</th><th>地址</th><th>余额</th></tr>';
  wallets.forEach(function(w) {
    html += '<tr><td><div style="font-weight:700">' + w.emoji + ' ' + w.name + '</div></td>' +
      '<td class="whale-hash">' + w.address.slice(0,12) + '...</td>' +
      '<td><span class="card-badge badge-purple">查询中</span></td></tr>';
  });
  html += '</table><div style="color:var(--muted);font-size:11px;margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">余额查询受API限制，点击地址可在Blockchain.com查看</div>';
  document.getElementById('walletTable').innerHTML = html;
}

function loadCongress() {
  fetch('/congress_trades')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data || !data.length) {
        document.getElementById('congressTable').innerHTML = '<div class="error-box">暂无数据</div>';
        return;
      }
      var html = '<table class="table"><tr><th>议员</th><th>股票代码</th><th>资产名称</th><th>交易类型</th><th>金额</th><th>日期</th></tr>';
      data.forEach(function(t) {
        var isBuy = t.type && t.type.toLowerCase().includes('purchase');
        html += '<tr>' +
          '<td style="font-weight:700">' + t.name + '</td>' +
          '<td style="font-weight:800;color:var(--accent)">' + t.ticker + '</td>' +
          '<td style="color:var(--muted);font-size:12px;max-width:200px">' + (t.asset||'').slice(0,40) + '</td>' +
          '<td><span class="' + (isBuy?'congress-buy':'congress-sell') + '">' + (isBuy?'买入':'卖出') + '</span></td>' +
          '<td style="font-weight:700">' + t.amount + '</td>' +
          '<td style="color:var(--muted);font-size:12px">' + t.date + '</td>' +
          '</tr>';
      });
      html += '</table>';
      document.getElementById('congressTable').innerHTML = html;
    })
    .catch(function() {
      document.getElementById('congressTable').innerHTML = '<div class="error-box">网络错误，请重试</div>';
    });
}

function refreshAll() {
  if (activeTab === 'institutions') selectFiler(activeFiler);
  if (activeTab === 'whales') loadWhales();
  if (activeTab === 'congress') loadCongress();
}

renderFilerGrid();
loadHoldings(filers[0].cik, filers[0].name);
setInterval(function() { if (activeTab === 'whales') loadWhales(); }, 30000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/sec_holdings")
def sec_holdings():
    cik = request.args.get("cik", "0001067983")
    data = get_sec_holdings(cik)
    if data:
        return jsonify(data)
    return jsonify({"error": "No data"}), 404

@app.route("/whale_txns")
def whale_txns():
    return jsonify(get_btc_whale_txns())

@app.route("/congress_trades")
def congress_trades():
    return jsonify(get_congress_trades())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
