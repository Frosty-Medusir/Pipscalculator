#!/usr/bin/env python3
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

LOG_FILE = os.path.expanduser("~/Downloads/pipscalculator/trades_log.csv")
CONFIG_FILE = os.path.expanduser("~/.pipcalc_config.json")
CACHE_TTL = 43200  # 12 hours

# Specs for your 5 core instruments:
# pip_size: price movement equal to 1 pip/point
# pip_val_usd: USD value per 1.00 standard lot per pip/point (UK100 uses live GBPUSD)
# decimals: price formatting precision for MT5
INSTRUMENTS = {
    "GBPUSD": {"pip_size": 0.0001, "pip_val_usd": 10.00, "decimals": 5, "unit": "pips"},
    "EURUSD": {"pip_size": 0.0001, "pip_val_usd": 10.00, "decimals": 5, "unit": "pips"},
    "XAUUSD": {"pip_size": 0.10,   "pip_val_usd": 10.00, "decimals": 2, "unit": "pips"},
    "XAGUSD": {"pip_size": 0.01,   "pip_val_usd": 50.00, "decimals": 3, "unit": "pips"},
    "UK100":  {"pip_size": 1.0,    "pip_val_usd": None,  "decimals": 1, "unit": "pts"},
}


def load_config() -> dict:
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"balance": 1000.0, "risk_pct": 1.0, "gbpusd_rate": 1.27, "rate_ts": 0}


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def get_gbpusd_rate(cfg: dict) -> float:
    now = time.time()
    if now - cfg.get("rate_ts", 0) < CACHE_TTL and cfg.get("gbpusd_rate"):
        return float(cfg["gbpusd_rate"])
    try:
        req = urllib.request.Request(
            "https://open.er-api.com/v6/latest/GBP",
            headers={"User-Agent": "pipcalc/1.0"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            rate = float(data["rates"]["USD"])
            cfg["gbpusd_rate"] = rate
            cfg["rate_ts"] = now
            save_config(cfg)
            return rate
    except Exception:
        return float(cfg.get("gbpusd_rate", 1.27))


def copy_to_clipboard(text: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        return False


def log_setup(row: dict) -> int:
    rows = []
    if os.path.isfile(LOG_FILE):
        with open(LOG_FILE, mode="r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    trade_id = len(rows) + 1
    row_with_id = {"id": trade_id, **row, "status": "OPEN", "r_result": ""}
    rows.append(row_with_id)
    with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row_with_id.keys()))
        writer.writeheader()
        writer.writerows(rows)
    return trade_id


def close_trade(trade_id: int, outcome: str) -> None:
    if not os.path.isfile(LOG_FILE):
        print("[!] No trades_log.csv found yet.")
        return
    with open(LOG_FILE, mode="r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    found = False
    for r in rows:
        if str(r.get("id")) == str(trade_id):
            found = True
            rr = float(r.get("rr", 3.0))
            if outcome == "win":
                r["status"] = "WIN"
                r["r_result"] = f"+{rr:g}"
            elif outcome == "loss":
                r["status"] = "LOSS"
                r["r_result"] = "-1"
            else:
                r["status"] = "BE"
                r["r_result"] = "0"
            break

    if not found:
        print(f"[!] Trade ID #{trade_id} not found.")
        return

    with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[+] Trade #{trade_id} marked as {outcome.upper()}.\n")


def show_stats() -> None:
    if not os.path.isfile(LOG_FILE):
        print("[!] No trades logged yet. Run a setup with --log first.")
        return
    with open(LOG_FILE, mode="r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    closed = [r for r in rows if r.get("status") in ("WIN", "LOSS", "BE")]
    wins = sum(1 for r in closed if r.get("status") == "WIN")
    losses = sum(1 for r in closed if r.get("status") == "LOSS")
    net_r = sum(float(r["r_result"]) for r in closed if r.get("r_result"))
    win_rate = (wins / len(closed) * 100.0) if closed else 0.0

    by_pair = {}
    for r in closed:
        p = r["pair"]
        by_pair[p] = by_pair.get(p, 0.0) + float(r["r_result"] or 0.0)

    print("\n" + "=" * 46)
    print("  PIPCALC PERFORMANCE STATS")
    print("=" * 46)
    print(f"  Total Setups    : {total} ({len(closed)} closed, {total - len(closed)} open)")
    print(f"  Win / Loss      : {wins}W / {losses}L ({win_rate:.1f}% win rate)")
    print(f"  Net Return      : {net_r:+.2f}R")
    if by_pair:
        print("-" * 46)
        for p, r_val in sorted(by_pair.items(), key=lambda x: x[1], reverse=True):
            print(f"  {p:<15} : {r_val:+.2f}R")
    print("=" * 46 + "\n")


def interactive_prompt(cfg: dict) -> argparse.Namespace:
    print("\n--- PIPCALC INTERACTIVE MODE ---")
    print("Supported: GBPUSD, EURUSD, XAUUSD, XAGUSD, UK100")
    pair = input("Pair [XAUUSD]: ").strip().upper() or "XAUUSD"
    bal_str = input(f"Balance USD [{cfg['balance']:g}]: ").strip()
    balance = float(bal_str) if bal_str else float(cfg["balance"])
    risk_str = input(f"Risk % [{cfg['risk_pct']:g}]: ").strip()
    risk_pct = float(risk_str) if risk_str else float(cfg["risk_pct"])
    sl_pips = float(input("Stop-Loss distance (pips/pts): ").strip())
    side = (input("Side (buy/sell) [buy]: ").strip().lower() or "buy")
    entry_str = input("Entry price (optional, Enter to skip): ").strip()
    entry = float(entry_str) if entry_str else None
    log_ans = input("Log this setup? (y/N): ").strip().lower() == "y"

    return argparse.Namespace(
        pair=pair,
        balance=balance,
        risk_pct=risk_pct,
        sl_pips=sl_pips,
        rr=3.0,
        entry=entry,
        side=side if side in ("buy", "sell") else "buy",
        log=log_ans,
    )


def run_calculation(args: argparse.Namespace, cfg: dict) -> None:
    pair = args.pair.upper().replace("/", "")
    if pair not in INSTRUMENTS:
        print(f"[!] Unsupported symbol '{pair}'. Allowed: {', '.join(INSTRUMENTS.keys())}")
        sys.exit(1)

    spec = INSTRUMENTS[pair]
    if pair == "UK100":
        gbpusd = get_gbpusd_rate(cfg)
        pip_val = 1.0 * gbpusd  # £1/pt converted to USD
    else:
        pip_val = spec["pip_val_usd"]

    cfg["balance"] = args.balance
    cfg["risk_pct"] = args.risk_pct
    save_config(cfg)

    risk_amount = args.balance * (args.risk_pct / 100.0)
    lot_size = risk_amount / (args.sl_pips * pip_val)
    tp_pips = args.sl_pips * args.rr
    reward_amount = risk_amount * args.rr
    unit = spec["unit"]
    decimals = spec["decimals"]

    sl_price = None
    tp_price = None
    if args.entry is not None:
        pip_size = spec["pip_size"]
        if args.side == "buy":
            sl_price = args.entry - (args.sl_pips * pip_size)
            tp_price = args.entry + (tp_pips * pip_size)
        else:
            sl_price = args.entry + (args.sl_pips * pip_size)
            tp_price = args.entry - (tp_pips * pip_size)

    lot_str = f"{lot_size:.2f}"
    copied = copy_to_clipboard(lot_str)

    print("\n" + "=" * 46)
    print(f"  {pair} | {args.side.upper()} | 1:{args.rr:g} R:R SETUP")
    print("=" * 46)
    print(f"  Account Balance : ${args.balance:,.2f}")
    print(f"  Risk ({args.risk_pct:g}%)       : ${risk_amount:,.2f}")
    print(f"  Target Profit   : ${reward_amount:,.2f}")
    print("-" * 46)
    print(f"  LOT SIZE        : {lot_str} lots {'(copied!)' if copied else ''}")
    print(f"  SL Distance     : {args.sl_pips:g} {unit}")
    print(f"  TP Distance     : {tp_pips:g} {unit}")
    if pair == "UK100":
        print(f"  UK100 Pt Value  : ${pip_val:.2f}/pt (GBPUSD {pip_val:.4f})")

    if args.entry is not None:
        print("-" * 46)
        print(f"  Entry Price     : {args.entry:.{decimals}f}")
        print(f"  Stop Loss (SL)  : {sl_price:.{decimals}f}")
        print(f"  Take Profit (TP): {tp_price:.{decimals}f}")

    print("=" * 46 + "\n")

    if args.log:
        trade_id = log_setup({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pair": pair,
            "side": args.side.upper(),
            "balance": f"{args.balance:.2f}",
            "risk_pct": args.risk_pct,
            "rr": args.rr,
            "risk_usd": f"{risk_amount:.2f}",
            "lot_size": lot_str,
            "sl_dist": args.sl_pips,
            "tp_dist": tp_pips,
            "entry": f"{args.entry:.{decimals}f}" if args.entry is not None else "",
            "sl_price": f"{sl_price:.{decimals}f}" if sl_price is not None else "",
            "tp_price": f"{tp_price:.{decimals}f}" if tp_price is not None else "",
        })
        print(f"[+] Logged as Trade #{trade_id} in {LOG_FILE}\n")


def main():
    cfg = load_config()

    if len(sys.argv) == 1:
        args = interactive_prompt(cfg)
        run_calculation(args, cfg)
        return

    if sys.argv[1] == "stats":
        show_stats()
        return

    if sys.argv[1] == "close":
        if len(sys.argv) < 4 or sys.argv[3].lower() not in ("win", "loss", "be"):
            print("Usage: pipcalc close <trade_id> <win|loss|be>")
            sys.exit(1)
        close_trade(int(sys.argv[2]), sys.argv[3].lower())
        return

    parser = argparse.ArgumentParser(
        description="Position size + 1:3 R:R calculator for GBPUSD, EURUSD, XAUUSD, XAGUSD, UK100."
    )
    parser.add_argument("pair", type=str, help="GBPUSD, EURUSD, XAUUSD, XAGUSD, or UK100")
    parser.add_argument("balance", type=float, help="Account balance in USD")
    parser.add_argument("risk_pct", type=float, help="Risk percentage per trade")
    parser.add_argument("sl_pips", type=float, help="Stop-loss distance in pips (or points for UK100)")
    parser.add_argument("--rr", type=float, default=3.0, help="Reward-to-Risk ratio (default: 3.0)")
    parser.add_argument("--entry", type=float, default=None, help="Optional entry price for MT5 SL/TP levels")
    parser.add_argument("--side", choices=["buy", "sell"], default="buy", help="Trade direction (default: buy)")
    parser.add_argument("--log", action="store_true", help="Log setup to trades_log.csv")

    args = parser.parse_args()
    run_calculation(args, cfg)


if __name__ == "__main__":
    main()
