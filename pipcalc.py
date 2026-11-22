#!/usr/bin/env python3
import argparse
import csv
import os
from datetime import datetime

# Approximate pip values per 1.00 standard lot (100,000 units; 100 oz for Gold)
PIP_VALUES = {
    "EURUSD": 10.00,
    "GBPUSD": 10.00,
    "AUDUSD": 10.00,
    "NZDUSD": 10.00,
    "USDJPY": 6.50,
    "GBPJPY": 6.50,
    "EURJPY": 6.50,
    "AUDCAD": 7.20,
    "USDCAD": 7.20,
    "XAUUSD": 10.00,  # $10 per $0.10 move (1 pip = 0.10 on standard MT5 Gold)
}

PIP_MULTIPLIERS = {
    "JPY": 0.01,
    "XAU": 0.10,
    "DEFAULT": 0.0001,
}

LOG_FILE = os.path.expanduser("~/Downloads/pipscalculator/trades_log.csv")


def get_pip_size(pair: str) -> float:
    if "JPY" in pair:
        return PIP_MULTIPLIERS["JPY"]
    if "XAU" in pair:
        return PIP_MULTIPLIERS["XAU"]
    return PIP_MULTIPLIERS["DEFAULT"]


def log_setup(row: dict) -> None:
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(
        description="Pre-session Forex & Gold position size + 1:3 R:R calculator."
    )
    parser.add_argument("pair", type=str, help="Symbol (e.g., XAUUSD, GBPJPY, EURUSD, AUDCAD)")
    parser.add_argument("balance", type=float, help="Account balance in USD")
    parser.add_argument("risk_pct", type=float, help="Risk percentage per trade (e.g., 1 or 2)")
    parser.add_argument("sl_pips", type=float, help="Stop-loss distance in pips")
    parser.add_argument("--rr", type=float, default=3.0, help="Reward-to-Risk ratio (default: 3.0)")
    parser.add_argument("--entry", type=float, default=None, help="Optional entry price to calculate exact SL/TP levels")
    parser.add_argument("--side", choices=["buy", "sell"], default="buy", help="Trade direction (default: buy)")
    parser.add_argument("--log", action="store_true", help="Append setup to trades_log.csv")

    args = parser.parse_args()
    pair = args.pair.upper().replace("/", "")

    if pair not in PIP_VALUES:
        print(f"[!] '{pair}' not in preset list. Defaulting to $10.00/pip.")
        pip_val = 10.00
    else:
        pip_val = PIP_VALUES[pair]

    risk_amount = args.balance * (args.risk_pct / 100.0)
    lot_size = risk_amount / (args.sl_pips * pip_val)
    tp_pips = args.sl_pips * args.rr
    reward_amount = risk_amount * args.rr

    sl_price = None
    tp_price = None
    decimals = 2 if "XAU" in pair else (3 if "JPY" in pair else 5)

    if args.entry is not None:
        pip_size = get_pip_size(pair)
        if args.side == "buy":
            sl_price = args.entry - (args.sl_pips * pip_size)
            tp_price = args.entry + (tp_pips * pip_size)
        else:
            sl_price = args.entry + (args.sl_pips * pip_size)
            tp_price = args.entry - (tp_pips * pip_size)

    print("\n" + "=" * 44)
    print(f"  {pair} | {args.side.upper()} | 1:{args.rr:g} R:R SETUP")
    print("=" * 44)
    print(f"  Account Balance : ${args.balance:,.2f}")
    print(f"  Risk ({args.risk_pct:g}%)       : ${risk_amount:,.2f}")
    print(f"  Target Profit   : ${reward_amount:,.2f}")
    print("-" * 44)
    print(f"  LOT SIZE        : {lot_size:.2f} lots")
    print(f"  SL Distance     : {args.sl_pips:g} pips")
    print(f"  TP Distance     : {tp_pips:g} pips")

    if args.entry is not None:
        print("-" * 44)
        print(f"  Entry Price     : {args.entry:.{decimals}f}")
        print(f"  Stop Loss (SL)  : {sl_price:.{decimals}f}")
        print(f"  Take Profit (TP): {tp_price:.{decimals}f}")

    print("=" * 44 + "\n")

    if args.log:
        log_setup({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pair": pair,
            "side": args.side.upper(),
            "balance": f"{args.balance:.2f}",
            "risk_pct": args.risk_pct,
            "risk_usd": f"{risk_amount:.2f}",
            "lot_size": f"{lot_size:.2f}",
            "sl_pips": args.sl_pips,
            "tp_pips": tp_pips,
            "entry": f"{args.entry:.{decimals}f}" if args.entry is not None else "",
            "sl_price": f"{sl_price:.{decimals}f}" if sl_price is not None else "",
            "tp_price": f"{tp_price:.{decimals}f}" if tp_price is not None else "",
        })
        print(f"[+] Saved setup to {LOG_FILE}\n")


if __name__ == "__main__":
    main()
