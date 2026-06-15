from pathlib import Path
from poe2_valuator_overlay import parse_item_text, HeuristicValuator, load_config

text = Path("sample_items.txt").read_text(encoding="utf-8")
blocks = [b for b in text.split("====================") if "Rarity:" in b]
config = load_config()
config["enable_market_lookup"] = False
valuator = HeuristicValuator(config, None)
for block in blocks:
    item = parse_item_text(block)
    result = valuator.value(item)
    print(item.display_name, item.category, item.stats)
    print(result.price_text, result.confidence, result.reasons[:2])
    print("---")
