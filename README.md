# Hermes Autonomous Hustle Engine

A permanent, self-contained AI agent that runs 24/7 on your VPS.
No Conway. No wallet-gated credits. Direct API calls only.

## Features

- **Daily autonomous loop**: Check health → Review funds → Scan opportunities → Execute → Report
- **GitHub bounty scanning**: Automatically finds paid issues
- **Wallet monitoring**: Tracks USDC balance on Base
- **Financial discipline**: Daily spending limits, expense tracking
- **Self-recovering**: Auto-restart on crash, state persistence
- **Transparent logging**: Every action logged with timestamps

## Deployment

### 1. Copy to VPS
```bash
scp -r hermes-agent/ root@your-vps:/root/
```

### 2. Set environment variables
Edit `/root/hermes-agent/hermes-agent.service` with your actual API keys.

### 3. Install systemd service
```bash
cp /root/hermes-agent/hermes-agent.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable hermes-agent
systemctl start hermes-agent
```

### 4. Monitor
```bash
journalctl -u hermes-agent -f
```

## Configuration

Edit `config.yaml`:
- `api.key`: LongCat API key (or use `LONGCAT_API_KEY` env var)
- `wallet.address`: Your Base wallet address
- `limits.max_daily_spend_usd`: Maximum daily API spend
- `limits.loop_interval_seconds`: How often to run the main loop

## State Files

- `ledger.json`: All financial transactions
- `crm.json`: Leads, customers, jobs
- `tasks.json`: Task queue and history
- `logs/`: Daily JSONL logs

## Security

- Never commit API keys to git
- Use environment variables for secrets
- Set strict file permissions: `chmod 600 config.yaml`
- Monitor logs regularly

## Cost Estimate

At $0.002/1k tokens and 1M tokens/day: ~$0.06/day = ~$1.80/month

## License

MIT
