# BTC Dip-Reversal Bot — make.fun btc-race-24h-20261118-1444

[![make.fun](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/enisaishere-hue/makefun-btc-race-24h/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/enisaishere-hue/makefun-btc-race-24h/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444)

A long-only cbBTC/USDC trading bot for [make.fun's "Race a BTC trading bot live for 24 hours"](https://make.fun/bounty/btc-race-24h-20261118-1444) ($250 USDC, top 10 paid). It trades 1-minute on-chain bars from Orca's cbBTC/USDC Whirlpool with $1,000 of paper money. Python 3.13, standard library only, deterministic.

## Strategy

The dev window falls −2.8% with one +2% mid-day recovery rally and a choppy sideways second half, so the bot is deliberately selective — it waits for a real wash-out plus a confirmed bounce instead of chasing 1-minute noise (a full-size round trip costs ~26–36 bps in fees, slippage and impact, while typical 1-minute moves are ~7 bps):

- **Main entry (dip-reversal):** close ≥ 150 bps below the 240-minute high **and** the last 30 minutes bounced ≥ 20 bps → buy with all cash. Fires rarely (3 bars in the whole dev window).
- **Fallback entry:** from bar 720, at most once a day, a milder dip (≥ 80 bps) with a ≥ 15 bps bounce → buy half the cash. Insurance so the bot still trades on a day with no big wash-out.
- **Exits:** take profit +200 bps (main) / +100 bps (fallback), trailing stop −100 bps / −60 bps from the peak close, or a max hold of 480 / 240 bars — whichever comes first. 30-bar cooldown after every exit.
- No trading in the first 240 bars (history warm-up) or after bar 1380.

## Dev-window result (local grade, official harness)

- **Net PnL: +$18.28** (2 round trips, max drawdown 0.6%)
- Trade 1: bought $63,903 at bar 271, sold $65,062 at bar 508 (rode the recovery rally)
- Trade 2 (fallback): bought $64,481 at bar 748, sold $64,654 at bar 988

Validated on split halves (first half +$17.32, second half $0.00 — it correctly sat out the choppy half instead of bleeding). Parameters were chosen for insensitivity: the main trade is identical across dip thresholds of 120–170 bps.

## Files

- `main.py` — the bot (speaks `agent-fun/bars-replay/v1` via the kit SDK)
- `vendor/makefun_bars.py` — the kit's Python SDK shim, copied byte-for-byte
- `LICENSE` — MIT

## Run it

```sh
python3 main.py  # speaks NDJSON on stdin/stdout; see the kit's grade-local
```
