# TruckLink AutoBot v8.3

Automated crypto trading bot for Telegram.

- OKX + Binance live trading
- Multi-timeframe technical + sentiment + fundamental analysis
- 3-tranche exits, break-even SL, trailing stop, time stop
- Native exchange stop-loss (survives bot downtime)
- TRC20 USDT subscription payments
- Self-marketing: channel auto-posts, referral rewards, leaderboard

## Deploy on Railway

1. Push to GitHub.
2. Railway → New Project → Deploy from GitHub.
3. Add a Volume mounted at `/data`.
4. Paste every key from `.env.example` into Railway → Variables.
5. Confirm Service is Worker (Procfile handles it).
6. Deploy.

## Generate ENCRYPTION_KEY

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

## Safety checklist

- [ ] ENCRYPTION_KEY set (32-byte Fernet key)
- [ ] USDT_WALLET is a valid T... TRC20 address
- [ ] ADMIN_IDS set
- [ ] Railway volume mounted at /data
- [ ] Tested with SANDBOX=True and demo keys first
- [ ] Backtest Sharpe > 0.5 across 6+ symbols over 180 days
