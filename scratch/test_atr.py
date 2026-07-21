from nautilus_trader.indicators import AverageTrueRange

atr = AverageTrueRange(14)
print("Initial ATR:", atr.value, type(atr.value), atr.initialized)

# Update with some values
for i in range(20):
    atr.update_raw(100.0 + i, 90.0 + i, 95.0 + i)
    print(f"Update {i+1}: ATR={atr.value}, initialized={atr.initialized}")
