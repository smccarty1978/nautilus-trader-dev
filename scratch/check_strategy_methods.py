from nautilus_trader.trading.strategy import Strategy

print("All dir(Strategy) entries containing 'order':")
for attr in sorted(dir(Strategy)):
    if "order" in attr.lower():
        print(" ", attr)
