"""
Compare an output stats.csv against the hand-checked answer key.

    python hd2stats.py <folder with the screenshots listed in answer_key.json>
    python dev/tests/check_accuracy.py output/stats.csv

Add more screenshots to answer_key.json whenever you check one by eye:
the bigger the key, the more you can trust a change to the code.
"""
import json
import sys
from pathlib import Path

import pandas as pd

key = json.loads((Path(__file__).parent / "answer_key.json").read_text())
stats = key["stats"]
df = pd.read_csv(sys.argv[1] if len(sys.argv) > 1 else "output/stats.csv")

total = wrong = wrong_flagged = flagged = missing = 0
for fname, players in key["screenshots"].items():
    d = df[df["file"] == fname].sort_values("slot")
    if d.empty:
        missing += 1
        continue
    for p, row in enumerate(d.to_dict("records")):
        fl = str(row.get("flagged_stats") or "")
        fl = [] if fl == "nan" else fl.split(", ")
        for st, want in zip(stats, players[p]):
            got = row[st]
            total += 1
            flagged += st in fl
            if pd.isna(got) or abs(float(got) - want) > 1e-6:
                wrong += 1
                wrong_flagged += st in fl
                print(f"WRONG  {fname}  player {p}  {st}: got {got}, expected {want}"
                      + ("  (flagged)" if st in fl else "  (NOT flagged!)"))
print(f"\n{total} values checked, {wrong} wrong ({wrong_flagged} of those were flagged), "
      f"{flagged} flagged for review" + (f", {missing} screenshots not in the output" if missing else ""))
sys.exit(1 if wrong - wrong_flagged else 0)
