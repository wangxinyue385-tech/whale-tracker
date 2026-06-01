from flask import Flask, request, jsonify, render_template_string
import requests
import os
import datetime
import re
import xml.etree.ElementTree as ET

app = Flask(__name__)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

SEC_FILERS = [
    {"name": "Berkshire Hathaway (Buffett)", "cik": "0001067983", "emoji": "🏦"},
    {"name": "Bridgewater Associates (Dalio)", "cik": "0001350694", "emoji": "🌉"},
    {"name": "Soros Fund Management", "cik": "0001029160", "emoji": "💰"},
    {"name": "Renaissance Technologies", "cik": "0001037389", "emoji": "🔬"},
    {"name": "Citadel Advisors", "cik": "0001423298", "emoji": "🏰"},
]

def get_btc_price():
    try:
        res = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            timeout=5
        )
        return res.json()["bitcoin"]["usd"]
    except:
        try:
            res = requests.get("https://mempool.space/api/v1/prices", timeout=5)
            return res.json().get("USD", 75000)
        except:
            return 75000

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

def get_btc_whale_txns():
    try:
        res = requests.get("https://mempool.space/api/mempool/recent", timeout=10)
        txns = res.json()
        btc_price = get_btc_price()
        big_txns = []
        for tx in txns:
            value_sat = tx.get("value", 0)
            value_btc = value_sat / 1e8
            if value_btc >= 10:
                big_txns.append({
                    "hash": tx.get("txid", "")[:16] + "...",
                    "value_btc": round(value_btc, 2),
                    "value_usd": round(value_btc * btc_price),
                    "fee": round(tx.get("fee", 0) / 1e8, 6),
                    "size": tx.get("size", 0),
                    "time": "pending"
                })
        big_txns.sort(key=lambda x: x["value_btc"], reverse=True)
        return big_txns[:20]
    except:
        try:
            res = requests.get(
                "https://blockchain.info/unconfirmed-transactions?format=json&limit=100",
                timeout=10
            )
            txns = res.json().get("txs", [])
            btc_price = get_btc_price()
            big_txns = []
            for tx in txns:
                out_value = sum(o.get("value", 0) for o in tx.get("out", [])) / 1e8
                if out_value >= 10:
                    big_txns.append({
                        "hash": tx["hash"][:16] + "...",
                        "value_btc": round(out_value, 2),
                        "value_usd": round(out_value * btc_price),
                        "fee": 0,
                        "size": tx.get("size", 0),
                        "time": "pending"
                    })
            big_txns.sort(key=lambda x: x["value_btc"], reverse=True)
            return big_txns[:20]
        except:
            return []

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
  display: flex; background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 24px; overflow-x: auto;
}
.tab {
  padding: 14px 20px; font-size: 13px; font-weight: 600;
  color: var(--muted); cursor: pointer; border: none; background: none;
  border-bottom: 2px solid transparent; white-space: nowrap; transition: all 0.2s;
}
.tab:hover { color: var(--accent); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }

.content { max-width: 1400px; margin: 0 auto; padding: 24px; }

.section-title { font-size: 20px; font-weight: 800; color: var(--text); margin-bottom: 6px; display: flex; align-items: center; gap: 10px; }
.section-sub { color: var(--muted); font-size: 13px; margin-bottom: 20px; }

.filer-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 20px; }
.filer-card {
  background: var(--surface); border: 1.5px solid var(--border);
  border-radius: 12px; padding: 14px; cursor: pointer; transition: all 0.2s;
}
.filer-card:hover, .filer-card.active { border-color: var(--accent); background: #f0f1ff; }
.filer-name { font-size: 13px; font-weight: 800; color: var(--text); margin-bottom: 4px; }
.filer-cik { font-size: 11px; color: var(--muted); }

.card {
  background: var(--surface); border: 1.5px solid var(--border);
  border-radius: 16px; padding: 20px;
  box-shadow: 0 4px 24px rgba(99,102,241,0.06);
  margin-bottom: 16px;
}
.card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.card-title { font-size: 15px; font-weight: 800; color: var(--text); display: flex; align-items: center; gap: 8px; }
.card-sub { color: var(--muted); font-size: 11px; margin-top: 3px; }
.card-badge { padding: 4px 10px; border-radius: 8px; font-size: 11px; font-weight: 700; }
.badge-purple { background: #f0f1ff; color: var(--accent); }
.badge-orange { background: var(--orange-bg); color: var(--orange); }

.total-box {
  background: linear-gradient(135deg, #f0f1ff, #f5f3ff);
  border: 1px solid #e0e7ff; border-radius: 12px;
  padding: 14px 16px; margin-bottom: 16px;
  display: flex; justify-content: space-between; align-items: center;
}
.total-label { font-size: 12px; color: var(--muted); font-weight: 600; }
.total-value { font-size: 22px; font-weight: 900; color: var(--accent); }

.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th { color: var(--muted); font-weight: 600; padding: 8px 10px; text-align: left; border-bottom: 1.5px solid var(--border); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
.table th:last-child { text-align: right; }
.table td { padding: 10px; border-top: 1px solid var(--border); color: var(--text2); vertical-align: middle; }
.table td:last-child { text-align: right; }
.table tr:hover td { background: #f8faff; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
.stat-card {
  background: var(--surface); border: 1.5px solid var(--border);
  border-radius: 14px; padding: 16px;
  box-shadow: 0 4px 16px rgba(99,102,241,0.05);
}
.stat-label { font-size: 11px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.stat-value { font-size: 22px; font-weight: 900; color: var(--text); }
.stat-sub { font-size: 11px; color: var(--muted); margin-top: 4px; }

.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 16px; }

.loading { text-align: center; padding: 40px; color: var(--muted); font-size: 14px; }
.spinner { display: inline-block; width: 24px; height: 24px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 10px; }
@keyframes spin { to { transform: rotate(360deg); } }
.error-box { text-align: center; padding: 30px; color: var(--muted); font-size: 13px; background: var(--surface2); border-radius: 12px; border: 1px dashed var(--border); }

.buy { color: var(--green); font-weight: 700; }
.sell { color: var(--red); font-weight: 700; }
.whale-hash { font-family: monospace; font-size: 11px; color: var(--muted); }
.hidden { display: none; }

.orange-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--orange); box-shadow: 0 0 6px var(--orange); animation: pulse 1.5s infinite; display: inline-block; }
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

  <div id="tab-institutions">
    <div class="section-title">🏦 机构持仓监控</div>
    <div class="section-sub">数据来源：SEC EDGAR 13F季报，每季度更新一次</div>
    <div class="filer-grid" id="filerGrid"></div>
    <div id="holdingsContent">
      <div class="loading"><div class="spinner"></div><br>加载持仓数据...</div>
    </div>
  </div>

  <div id="tab-whales" class="hidden">
    <div class="section-title">🐋 加密巨鲸实时监控</div>
    <div class="section-sub">实时监控BTC链上大额交易（≥10 BTC），数据来源：mempool.space</div>
    <div class="stat-row">
      <div class="stat-card"><div class="stat-label">监控交易数</div><div class="stat-value" id="stat-txns">--</div><div class="stat-sub">≥10 BTC</div></div>
      <div class="stat-card"><div class="stat-label">最大单笔</div><div class="stat-value" id="stat-max">--</div><div class="stat-sub">BTC</div></div>
      <div class="stat-card"><div class="stat-label">总转移量</div><div class="stat-value" id="stat-total">--</div><div class="stat-sub">BTC</div></div>
      <div class="stat-card"><div class="stat-label">折合美元</div><div class="stat-value" id="stat-usd">--</div><div class="stat-sub">USD</div></div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title"><span class="orange-dot"></span> 实时大额交易</div>
            <div class="card-sub">BTC链上 ≥10 BTC 大额转账</div>
          </div>
          <span class="card-badge badge-orange">LIVE</span>
        </div>
        <div id="whaleTable"><div class="loading"><div class="spinner"></div><br>加载中...</div></div>
      </div>
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">📍 知名钱包监控</div>
            <div class="card-sub">交易所和机构主要冷钱包</div>
          </div>
          <span class="card-badge badge-purple">WATCH</span>
        </div>
        <div id="walletTable"></div>
      </div>
    </div>
  </div>

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
      <div id="congressTable"><div class="loading"><div class="spinner"></div><br>加载中...</div></div>
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
      '<div class="filer-cik">CIK: ' + f.cik + '</div></div>';
  }).join('');
}

function selectFiler(idx) {
  activeFiler = idx;
  renderFilerGrid();
  loadHoldings(filers[idx].cik, filers[idx].name);
}

function loadHoldings(cik, name) {
  var box = document.getElementById('holdingsContent');
  box.innerHTML = '<div class="loading"><div class="spinner"></div><br>从SEC EDGAR获取数据，请稍候...</div>';
  fetch('/sec_holdings?cik=' + encodeURIComponent(cik))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data || !data.holdings || !data.holdings.length) {
        box.innerHTML = '<div class="error-box">⚠️ ' + (data.error || '暂无数据，请稍后重试') + '</div>';
        return;
      }
      var total = data.total ? '$' + (data.total/1e9).toFixed(2) + 'B' : 'N/A';
      var html = '<div class="card">' +
        '<div class="card-header"><div><div class="card-title">' + name + ' 持仓明细</div>' +
        '<div class="card-sub">报告日期：' + data.date + '</div></div>' +
        '<span class="card-badge badge-purple">13F-HR</span></div>' +
        '<div class="total-box"><div class="total-label">总持仓市值</div><div class="total-value">' + total + '</div></div>' +
        '<table class="table"><tr><th>#</th><th>股票名称</th><th>持仓市值</th><th style="text-align:right">持仓份额</th></tr>';
      data.holdings.forEach(function(h, i) {
        html += '<tr><td style="color:var(--muted);font-size:12px">' + (i+1) + '</td>' +
          '<td style="font-weight:700">' + h.name + '</td>' +
          '<td style="font-weight:700;color:var(--accent)">$' + (h.value/1e6).toFixed(1) + 'M</td>' +
          '<td style="color:var(--muted);text-align:right">' + h.shares.toLocaleString() + '</td></tr>';
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
      var html = '<table class="table"><tr><th>交易Hash</th><th>BTC金额</th><th>USD价值</th><th style="text-align:right">手续费</th></tr>';
      data.forEach(function(t) {
        var big = t.value_btc >= 100;
        html += '<tr>' +
          '<td class="whale-hash">' + t.hash + '</td>' +
          '<td style="font-weight:800;color:' + (big?'var(--orange)':'var(--text)') + '">' + t.value_btc.toLocaleString() + ' BTC</td>' +
          '<td style="color:var(--muted);font-size:12px">$' + t.value_usd.toLocaleString() + '</td>' +
          '<td style="color:var(--muted);font-size:12px;text-align:right">' + t.fee + ' BTC</td>' +
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
    {name:"Huobi Exchange", address:"1HckjUpRGcrrRAtFaaCAUaGjsPx9oYmLaZ", emoji:"🔥"},
  ];
  var html = '<table class="table"><tr><th>钱包名称</th><th>地址（前12位）</th><th style="text-align:right">链接</th></tr>';
  wallets.forEach(function(w) {
    html += '<tr>' +
      '<td style="font-weight:700">' + w.emoji + ' ' + w.name + '</td>' +
      '<td class="whale-hash">' + w.address.slice(0,12) + '...</td>' +
      '<td style="text-align:right"><a href="https://www.blockchain.com/btc/address/' + w.address + '" target="_blank" style="color:var(--accent);font-size:12px">查看 ↗</a></td>' +
      '</tr>';
  });
  html += '</table><div style="color:var(--muted);font-size:11px;margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">点击查看链接可在Blockchain.com查看完整余额和交易记录</div>';
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
      var html = '<table class="table"><tr><th>议员</th><th>政党</th><th>股票代码</th><th>资产名称</th><th>操作</th><th>金额</th><th style="text-align:right">日期</th></tr>';
      data.forEach(function(t) {
        html += '<tr>' +
          '<td style="font-weight:700">' + t.name + '</td>' +
          '<td style="color:var(--muted);font-size:12px">' + (t.party||'') + '</td>' +
          '<td style="font-weight:800;color:var(--accent)">' + t.ticker + '</td>' +
          '<td style="color:var(--muted);font-size:12px">' + (t.asset||'') + '</td>' +
          '<td><span class="' + (t.is_buy?'buy':'sell') + '">' + t.type + '</span></td>' +
          '<td style="font-weight:600">' + t.amount + '</td>' +
          '<td style="color:var(--muted);font-size:12px;text-align:right">' + t.date + '</td>' +
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
    return jsonify(data)

@app.route("/whale_txns")
def whale_txns():
    return jsonify(get_btc_whale_txns())

@app.route("/congress_trades")
def congress_trades():
    return jsonify(get_congress_trades())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
