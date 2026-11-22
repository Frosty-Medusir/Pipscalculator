#!/usr/bin/env python3
"""
pipcalc - position size + R:R calculator for GBPUSD, EURUSD, XAUUSD, XAGUSD, UK100.

Stop-loss can be given three ways (use exactly one):
  --sl PRICE        absolute stop-loss price (needs --entry; side is inferred)
  --sl-dist DIST    stop-loss distance in PRICE units (e.g. 5 on XAUUSD = a $5 move)
  --sl-pips PIPS    stop-loss distance in pips/points (the old behaviour)
"""
import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

LOG_FILE = os.path.expanduser("~/Downloads/Pipscalculator/trades_log.csv")
CONFIG_FILE = os.path.expanduser("~/.pipcalc_config.json")
CACHE_TTL = 43200  # 12 hours

LOT_STEP = 0.01  # change if your broker uses a different lot step
MIN_LOT = 0.01   # smallest lot your broker allows

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


def die(msg: str) -> None:
    print(f"[!] {msg}")
    sys.exit(1)


# --------------------------------------------------------------------------
# Config + live rate
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Trade log
# --------------------------------------------------------------------------
def log_setup(row: dict) -> int:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
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


# --------------------------------------------------------------------------
# Interactive mode
# --------------------------------------------------------------------------
def ask_float(label: str, default=None, optional: bool = False):
    """Prompt until a valid number is typed. Enter accepts the default."""
    shown = f" [{default:g}]" if default is not None else ""
    while True:
        raw = input(f"{label}{shown}: ").strip()
        if not raw:
            if default is not None:
                return float(default)
            if optional:
                return None
            print("  Please enter a number.")
            continue
        try:
            return float(raw)
        except ValueError:
            print("  Not a valid number, try again.")


def interactive_prompt(cfg: dict) -> argparse.Namespace:
    print("\n--- PIPCALC INTERACTIVE MODE ---")
    print("Supported: GBPUSD, EURUSD, XAUUSD, XAGUSD, UK100")
    default_pair = cfg.get("pair", "XAUUSD")
    pair = input(f"Pair [{default_pair}]: ").strip().upper() or default_pair
    balance = ask_float("Balance USD", cfg["balance"])
    risk_pct = ask_float("Risk %", cfg["risk_pct"])
    rr = ask_float("R:R", 3.0)
    entry = ask_float("Entry price (Enter to skip)", optional=True)

    sl_price = sl_dist = None
    side = None
    if entry is not None:
        sl_price = ask_float("Stop-loss PRICE")  # side is inferred from this
    else:
        sl_dist = ask_float("Stop-loss distance in price units (e.g. 5 = $5 move on gold)")
        side = (input("Side (buy/sell) [buy]: ").strip().lower() or "buy")
        if side not in ("buy", "sell"):
            side = "buy"

    log_ans = input("Log this setup? (y/N): ").strip().lower() == "y"

    cfg["pair"] = pair
    return argparse.Namespace(
        pair=pair,
        balance=balance,
        risk_pct=risk_pct,
        sl_price=sl_price,
        sl_dist=sl_dist,
        sl_pips=None,
        rr=rr,
        entry=entry,
        side=side,
        log=log_ans,
    )


# --------------------------------------------------------------------------
# Core calculation
# --------------------------------------------------------------------------
def resolve_stop(args: argparse.Namespace, pip_size: float):
    """
    Turn whichever stop-loss input was given into:
      dist  - stop distance in price units
      pips  - stop distance in pips/points
      side  - 'buy' or 'sell'
    """
    given = [n for n in ("sl_price", "sl_dist", "sl_pips") if getattr(args, n, None) is not None]
    if len(given) != 1:
        die("Give exactly one stop-loss: --sl PRICE, --sl-dist DISTANCE, or --sl-pips PIPS.")

    side = args.side

    if args.sl_price is not None:
        if args.entry is None:
            die("--sl (stop-loss price) needs --entry so the distance can be worked out.")
        if args.sl_price == args.entry:
            die("Stop-loss price equals the entry price.")
        inferred = "buy" if args.sl_price < args.entry else "sell"
        if side is not None and side != inferred:
            die(
                f"Stop-loss {args.sl_price:g} is {'below' if inferred == 'buy' else 'above'} "
                f"entry {args.entry:g}, which means a {inferred.upper()}, "
                f"but you asked for {side.upper()}."
            )
        side = inferred
        dist = abs(args.entry - args.sl_price)
    elif args.sl_dist is not None:
        dist = args.sl_dist
    else:
        dist = args.sl_pips * pip_size

    if dist <= 0:
        die("Stop-loss distance must be greater than zero.")

    return dist, dist / pip_size, (side or "buy")


def run_calculation(args: argparse.Namespace, cfg: dict) -> None:
    pair = args.pair.upper().replace("/", "")
    if pair not in INSTRUMENTS:
        die(f"Unsupported symbol '{pair}'. Allowed: {', '.join(INSTRUMENTS.keys())}")
    if args.balance <= 0:
        die("Balance must be greater than zero.")
    if args.risk_pct <= 0:
        die("Risk % must be greater than zero.")
    if args.rr <= 0:
        die("R:R must be greater than zero.")

    spec = INSTRUMENTS[pair]
    pip_size = spec["pip_size"]
    decimals = spec["decimals"]
    unit = spec["unit"]

    if pair == "UK100":
        gbpusd = get_gbpusd_rate(cfg)
        pip_val = 1.0 * gbpusd  # £1/pt converted to USD
    else:
        pip_val = spec["pip_val_usd"]

    sl_dist, sl_pips, side = resolve_stop(args, pip_size)

    cfg["balance"] = args.balance
    cfg["risk_pct"] = args.risk_pct
    cfg["pair"] = pair
    save_config(cfg)

    risk_amount = args.balance * (args.risk_pct / 100.0)

    # Round the lot size DOWN to the broker's lot step so risk never exceeds the limit.
    lot_exact = risk_amount / (sl_pips * pip_val)
    lot_size = round(math.floor(lot_exact / LOT_STEP + 1e-9) * LOT_STEP, 2)

    if lot_size < MIN_LOT:
        min_risk = MIN_LOT * sl_pips * pip_val
        print("\n[!] Stop-loss is too wide for this risk amount.")
        print(f"    Exact lot size is {lot_exact:.4f}, below the minimum lot of {MIN_LOT:.2f}.")
        print(f"    The minimum lot would risk ${min_risk:,.2f} "
              f"({min_risk / args.balance * 100:.2f}% of balance) instead of ${risk_amount:,.2f}.")
        print("    Tighten the stop, raise the risk %, or skip this trade. Nothing copied or logged.\n")
        return

    actual_risk = lot_size * sl_pips * pip_val
    actual_risk_pct = actual_risk / args.balance * 100.0
    tp_dist = sl_dist * args.rr
    tp_pips = sl_pips * args.rr
    reward_amount = actual_risk * args.rr

    sl_price = args.sl_price
    tp_price = None
    if args.entry is not None:
        if side == "buy":
            sl_price = args.entry - sl_dist
            tp_price = args.entry + tp_dist
        else:
            sl_price = args.entry + sl_dist
            tp_price = args.entry - tp_dist

    lot_str = f"{lot_size:.2f}"
    copied = copy_to_clipboard(lot_str)

    print("\n" + "=" * 46)
    print(f"  {pair} | {side.upper()} | 1:{args.rr:g} R:R SETUP")
    print("=" * 46)
    print(f"  Account Balance : ${args.balance:,.2f}")
    print(f"  Max Risk ({args.risk_pct:g}%)   : ${risk_amount:,.2f}")
    print(f"  Actual Risk     : ${actual_risk:,.2f} ({actual_risk_pct:.2f}%)")
    print(f"  Target Profit   : ${reward_amount:,.2f}")
    print("-" * 46)
    print(f"  LOT SIZE        : {lot_str} lots {'(copied!)' if copied else ''}")
    print(f"  SL Distance     : {sl_dist:.{decimals}f} price ({sl_pips:g} {unit})")
    print(f"  TP Distance     : {tp_dist:.{decimals}f} price ({tp_pips:g} {unit})")
    if pair == "UK100":
        print(f"  UK100 Pt Value  : ${pip_val:.2f}/pt (GBPUSD {gbpusd:.4f})")

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
            "side": side.upper(),
            "balance": f"{args.balance:.2f}",
            "risk_pct": args.risk_pct,
            "rr": args.rr,
            "risk_usd": f"{actual_risk:.2f}",
            "lot_size": lot_str,
            "sl_dist": round(sl_pips, 2),   # still stored in pips/pts so old rows stay comparable
            "tp_dist": round(tp_pips, 2),
            "entry": f"{args.entry:.{decimals}f}" if args.entry is not None else "",
            "sl_price": f"{sl_price:.{decimals}f}" if sl_price is not None else "",
            "tp_price": f"{tp_price:.{decimals}f}" if tp_price is not None else "",
        })
        print(f"[+] Logged as Trade #{trade_id} in {LOG_FILE}\n")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
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
        description="Position size + R:R calculator for GBPUSD, EURUSD, XAUUSD, XAGUSD, UK100.",
        epilog=(
            "examples:\n"
            "  pipcalc XAUUSD 1000 1 --entry 4000 --sl 3995     (SL as a price, side inferred)\n"
            "  pipcalc XAUUSD 1000 1 --sl-dist 5                (SL = a $5 move, side defaults to buy)\n"
            "  pipcalc EURUSD 1000 1 --sl-pips 15 --side sell   (SL in pips)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pair", type=str, help="GBPUSD, EURUSD, XAUUSD, XAGUSD, or UK100")
    parser.add_argument("balance", type=float, help="Account balance in USD")
    parser.add_argument("risk_pct", type=float, help="Risk percentage per trade")

    stop = parser.add_argument_group("stop-loss (give exactly one)")
    stop.add_argument("--sl", "--sl-price", dest="sl_price", type=float, default=None,
                      help="Stop-loss PRICE (requires --entry; buy/sell is inferred)")
    stop.add_argument("--sl-dist", dest="sl_dist", type=float, default=None,
                      help="Stop-loss distance in price units (e.g. 5 = $5 move on XAUUSD)")
    stop.add_argument("--sl-pips", dest="sl_pips", type=float, default=None,
                      help="Stop-loss distance in pips (points for UK100)")

    parser.add_argument("--rr", type=float, default=3.0, help="Reward-to-Risk ratio (default: 3.0)")
    parser.add_argument("--entry", type=float, default=None, help="Entry price (unlocks SL/TP prices)")
    parser.add_argument("--side", choices=["buy", "sell"], default=None,
                        help="Trade direction (inferred from --sl when possible, else buy)")
    parser.add_argument("--log", action="store_true", help="Log setup to trades_log.csv")

    args = parser.parse_args()
    run_calculation(args, cfg)


if __name__ == "__main__":
    main()