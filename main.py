"""Dip-reversal BTC trading bot for make.fun btc-race-24h-20261118-1444.

Long-only cbBTC/USDC bot on 1-minute on-chain bars (agent-fun/bars-replay/v1).
Standard library only, fully deterministic (integer math, no clock, no
randomness, no network, no files).

Strategy (designed from the published dev window, validated on its split
halves; the dev window falls -2.8% with one +2% mid-day recovery rally and a
choppy sideways second half, so the bot is deliberately selective):
  * Main entry (dip-reversal): once the close is at least 150 bps below the
    240-minute high AND the last 30 minutes bounced at least 20 bps, buy with
    all cash. This fires rarely (3 bars in the whole dev window) and only
    after a real wash-out plus a confirmed bounce, so it never chases noise.
  * Fallback entry: from bar 720, a milder dip (80 bps below the 240-minute
    high) with a 15 bps 30-minute bounce buys half the cash. Insurance so the
    bot still trades on a day with no big wash-out. It re-arms 240 bars after
    its last entry: if the first fallback trade exits early, a later mild dip
    can still be traded instead of the bot sitting out the rest of the day.
  * Exits: take profit +200 bps (main) / +100 bps (fallback), trailing stop
    -100 bps / -60 bps from the peak close, or a max hold of 480 / 240 bars,
    whichever comes first. A 30-bar cooldown follows every exit.
  * Nothing is traded in the first 240 bars (the high window needs history)
    or after bar 1380 (a fresh trade cannot develop before the window ends).

Costs: every full-size round trip pays ~26-36 bps (4 bps fee + 2 bps
slippage + ~12 bps impact per leg at the dev window's ~$850k depth), so a
trade must catch a move larger than that; the exits above are sized for it.
max_slippage_bps is 250, far above any 1-minute move in the dev window
(max under 100 bps) so orders are not rejected on ordinary gaps, while
still capping a fill in a violent gap.

Position state is read from the harness-reported account every batch, so a
rejected order can never leave the bot's bookkeeping out of sync with the
market: if a buy is rejected the entry tracking is cleared and the bot
re-evaluates from the next bar.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
MAX_SLIPPAGE_BPS = 250
MIN_NOTIONAL = 1_000_000  # 1 USDC, in micro-USDC

WARMUP_BARS = 240        # bars of history needed for the 240-minute high
LAST_ENTRY_BAR = 1380    # no fresh entries in the final hour
COOLDOWN_BARS = 30       # bars to wait after any exit

# Main setup: deep dip + confirmed bounce, full size.
DIP_MAIN_BPS = 150
BOUNCE_MAIN_BPS = 20
TP_MAIN_BPS = 200
TRAIL_MAIN_BPS = 100
HOLD_MAIN_BARS = 480

# Fallback setup: milder dip + bounce, half size, from bar 720, re-arming
# 240 bars after its last entry (so an early exit does not end the day).
FB_FROM_BAR = 720
FB_REARM_BARS = 240
DIP_FB_BPS = 80
BOUNCE_FB_BPS = 15
TP_FB_BPS = 100
TRAIL_FB_BPS = 60
HOLD_FB_BARS = 240


class Bot:
    def __init__(self):
        self.closes = []          # closes seen so far, ints at price_scale 5
        self.entry_close = None   # close of the bar the current trade was decided on
        self.peak_close = None    # highest close since entry
        self.entry_bar = None     # seq of the bar the current trade was decided on
        self.mode = None          # 'dip' or 'fb'
        self.fb_last_bar = None   # seq of the last fallback entry (re-arms later)
        self.cooldown_until = -1
        self.buy_sent_seq = None  # seq a buy was sent on, awaiting its fill report

    def _bps(self, now, ref):
        """(now/ref - 1) in bps, integer math, truncating toward zero."""
        return (now - ref) * 10_000 // ref

    def on_batch(self, state, batch):
        bars = [b for b in batch.get("bars", []) if b.get("symbol") == SYMBOL]
        if not bars:
            return []
        close = int(bars[0]["c"])
        self.closes.append(close)
        seq = state.seq

        held = state.positions.get(SYMBOL)
        qty = held.qty if held is not None else 0

        # Reconcile with the harness-reported account.
        if qty == 0:
            if self.buy_sent_seq is not None and seq == self.buy_sent_seq + 1:
                # The buy decided on the previous batch was rejected at its
                # fill (e.g. max_slippage): clear it and wait a few bars.
                self.cooldown_until = max(self.cooldown_until, seq + 5)
            self.buy_sent_seq = None
            self.entry_close = None
            self.peak_close = None
            self.entry_bar = None
            self.mode = None
        else:
            self.buy_sent_seq = None
            if self.entry_close is None:
                # Position held without our own entry record (should not
                # happen): anchor on the current close so exits still work.
                self.entry_close = close
                self.peak_close = close
                self.entry_bar = seq
                self.mode = "dip"

        if qty > 0:
            # In a position: manage the exit.
            self.peak_close = max(self.peak_close, close)
            bars_in = seq - self.entry_bar
            up_bps = self._bps(close, self.entry_close)
            dd_bps = self._bps(close, self.peak_close)
            if self.mode == "fb":
                tp, trail, hold = TP_FB_BPS, TRAIL_FB_BPS, HOLD_FB_BARS
            else:
                tp, trail, hold = TP_MAIN_BPS, TRAIL_MAIN_BPS, HOLD_MAIN_BARS
            if up_bps >= tp or dd_bps <= -trail or bars_in >= hold:
                self.cooldown_until = seq + COOLDOWN_BARS
                return [{"side": "sell", "symbol": SYMBOL, "qty": qty,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            return []

        # Flat: look for an entry.
        if seq < WARMUP_BARS or seq > LAST_ENTRY_BAR or seq < self.cooldown_until:
            return []
        if len(self.closes) < WARMUP_BARS + 1:
            return []
        hist = self.closes[:-1]  # bars before the current one
        hi240 = max(hist[-WARMUP_BARS:])
        dip_bps = self._bps(close, hi240)
        bounce_bps = self._bps(close, self.closes[-31])  # 30 bars back
        if dip_bps <= -DIP_MAIN_BPS and bounce_bps >= BOUNCE_MAIN_BPS:
            notional = state.cash
            if notional < MIN_NOTIONAL:
                return []
            self.entry_close = close
            self.peak_close = close
            self.entry_bar = seq
            self.mode = "dip"
            self.buy_sent_seq = seq
            return [{"side": "buy", "symbol": SYMBOL,
                     "notional_quote_units": notional,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        if (seq >= FB_FROM_BAR
                and (self.fb_last_bar is None
                     or seq - self.fb_last_bar >= FB_REARM_BARS)
                and dip_bps <= -DIP_FB_BPS and bounce_bps >= BOUNCE_FB_BPS):
            notional = state.cash // 2
            if notional < MIN_NOTIONAL:
                return []
            self.entry_close = close
            self.peak_close = close
            self.entry_bar = seq
            self.mode = "fb"
            self.fb_last_bar = seq
            self.buy_sent_seq = seq
            return [{"side": "buy", "symbol": SYMBOL,
                     "notional_quote_units": notional,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []


def main():
    bot = Bot()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
