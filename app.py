      };
      ws.onmessage = event => {
        state.tradeMessages++;
        const payload = JSON.parse(event.data).data || {};
        const symbol = payload.s;
        if (!symbol || !WATCH_SYMBOLS.includes(symbol)) return;
        const ts = payload.T || Date.now();
        const priceValue = Number(payload.p || 0);
        const qty = Number(payload.q || 0);
        const notional = priceValue * qty;
        const side = payload.m ? "SELL" : "BUY";
        rememberPrice(symbol, priceValue, ts);
        if (notional >= LARGE_TRADE_USD) {
          const row = {symbol, side, ts, price: priceValue, qty, notional};
          ensureList(state.trades, symbol).push(row);
          addEvent({...row, label: side === "BUY" ? "主动买" : "主动卖"});
        }
      };
    }
    function connectLiquidations() {
      connectLiquidationEndpoint(0);
    }
    function connectLiquidationEndpoint(index) {
      const baseUrl = BINANCE_WS_BASES[index % BINANCE_WS_BASES.length];
      const ws = new WebSocket(`${baseUrl}/ws/!forceOrder@arr`);
      state.sockets.push(ws);
      let opened = false;
      let movedOn = false;
      const tryNext = () => {
        if (movedOn) return;
        movedOn = true;
        setTimeout(() => connectLiquidationEndpoint(index + 1), 900);
      };
      const timeoutId = setTimeout(() => {
        if (!opened && ws.readyState === WebSocket.CONNECTING) {
          state.liqError = `爆仓流连接超时：${baseUrl}`;
          renderRadar();
          try { ws.close(); } catch (_) {}
          tryNext();
        }
      }, 8000);
      ws.onopen = () => {
        opened = true;
        clearTimeout(timeoutId);
        state.liqConnected = true;
        state.liqError = "";
        renderRadar();
      };
      ws.onclose = () => {
        clearTimeout(timeoutId);
        state.liqConnected = false;
        renderRadar();
        if (opened) setTimeout(() => connectLiquidationEndpoint(index), 3000);
        else tryNext();
      };
      ws.onerror = () => {
        state.liqError = `浏览器无法连接 Binance 爆仓流：${baseUrl}`;
        renderRadar();
      };
      ws.onmessage = event => {
        state.liqMessages++;
        const payload = JSON.parse(event.data);
        const order = payload.o || {};
        const symbol = order.s;
        if (!symbol || !WATCH_SYMBOLS.includes(symbol)) return;
        const priceValue = Number(order.ap || order.p || 0);
        const qty = Number(order.q || 0);
        const notional = priceValue * qty;
        if (notional < LARGE_TRADE_USD) return;
        const side = order.S || "";
        const ts = order.T || payload.E || Date.now();
        const row = {symbol, side, ts, price: priceValue, qty, notional};
        ensureList(state.liquidations, symbol).push(row);
        addEvent({...row, label: side === "BUY" ? "空爆" : "多爆"});
      };
    }
    function start() {
      closeSockets();
      connectPrices();
      connectTrades();
      connectLiquidations();
      renderRadar();
      renderEvents();
    }
    document.getElementById("refresh").addEventListener("click", start);
    document.getElementById("aiBtn").addEventListener("click", runAiAnalysis);
    document.getElementById("search").addEventListener("input", renderRadar);
    document.getElementById("filters").addEventListener("click", event => {
      if (!event.target.dataset.filter) return;
      state.activeFilter = event.target.dataset.filter;
      document.querySelectorAll("#filters button").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.filter === state.activeFilter);
      });
      renderRadar();
    });
    setInterval(() => { trimOldData(); renderRadar(); renderEvents(); }, 1000);
    start();
  </script>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    html = HTML.replace("__WATCH_SYMBOLS__", json.dumps(WATCH_SYMBOLS))
    html = html.replace("__LARGE_TRADE_USD__", json.dumps(LARGE_TRADE_USD))
    html = html.replace("__BINANCE_WS_BASES__", json.dumps(BINANCE_WS_BASES))
    return render_template_string(html)


@app.route("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "mode": "browser_direct_binance_websocket",
            "watch_symbols": WATCH_SYMBOLS,
            "large_trade_usd": LARGE_TRADE_USD,
            "binance_ws_bases": BINANCE_WS_BASES,
        }
    )


@app.route("/debug/binance")
def debug_binance():
    return jsonify(
        {
            "message": "Render no longer fetches Binance. The browser connects directly to Binance WebSocket.",
            "binance_ws_bases": BINANCE_WS_BASES,
        }
    )


@app.post("/api/ai/analyze")
def ai_analyze():
    payload = request.get_json(silent=True) or {}
    fallback = rule_based_analysis(payload)
    analysis, mode = call_ai_analysis(payload, fallback)
    return jsonify(
        {
            "analysis": analysis,
            "mode": mode,
            "model": AI_MODEL if mode == "ai" else None,
            "has_ai_key": bool(AI_API_KEY),
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
