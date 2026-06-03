# Binance Flow Radar

Binance Flow Radar 是一个 Flask 托管的前端资金流监控网站。

它会监控：

- Binance USDT 永续合约价格流
- 浏览器直连 Binance WebSocket 的实时大额主动成交
- 浏览器直连 Binance WebSocket 的实时强平/爆仓订单
- 60 秒和 5 分钟资金净流
- 5 分钟价格变化

Render 服务器不直接请求 Binance。Binance 会限制 Render 等云服务器出口地区，因此行情在用户浏览器里直接连接 Binance WebSocket。

## 本地运行

```bash
pip install -r requirements.txt
python app.py
```

打开：

```text
http://localhost:5000
```

## Render 部署

仓库里已经包含 `render.yaml`，推到 GitHub 后可以在 Render 里用 Blueprint 部署。

常用环境变量：

- `LARGE_TRADE_USD`: 大额成交阈值，默认 `80000`
- `WATCH_SYMBOLS`: WebSocket 实时监听交易对，逗号分隔
- `BINANCE_WS_BASES`: Binance WebSocket market 路由，默认 `wss://fstream.binance.com/market,wss://fstream.binancefuture.com/market`
- `DEEPSEEK_API_KEY`: 可选，启用 AI 分析
- `AI_API_KEY`: 可选，通用 OpenAI-compatible API Key
- `AI_API_BASE`: 可选，通用 OpenAI-compatible API Base
- `AI_MODEL`: 可选，默认 DeepSeek 使用 `deepseek-chat`

示例：

```text
WATCH_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WIFUSDT,1000PEPEUSDT
```

## 风险说明

这个工具只用于缩小观察范围，不构成投资建议。公开行情不需要登录币安账户，也不需要 API Key。不要把交易账户、密码或 API 密钥放进这个网站。

AI 分析只读取当前页面的公开行情快照，不读取账户，不自动下单。
