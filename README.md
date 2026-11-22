# pipscalculator

A zero-dependency Python CLI tool for pre-session Forex and Gold (XAUUSD) position sizing, lot calculation, and 1:3 Risk-to-Reward execution levels.

## Setup

    chmod +x ~/Downloads/Pipscalculator/pipcalc.py
    echo 'alias pipcalc="python3 ~/Downloads/Pipscalculator/pipcalc.py"' >> ~/.zshrc
    source ~/.zshrc

## Usage

    # Quick lot size check
    pipcalc GBPJPY 500 1 25

    # Full MT5 price levels + CSV logging
    pipcalc XAUUSD 1000 1.5 40 --entry 2650.00 --side buy --log
