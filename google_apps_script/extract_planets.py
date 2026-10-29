import sys, re, unicodedata
src = open(sys.argv[1], encoding="utf-8-sig").read().splitlines()
recs, odd = {}, []
for i, l in enumerate(src):
    f = [x.strip() for x in l.split("\t")]
    if len(f) < 3 or not f[0]: continue
    if re.search(r"\.(png|jpe?g|webp|gif|svg)$", f[1], re.I) or f[1] == "":
        name, sector = f[0], f[2]
        if not (sector.endswith(" Sector") or sector in ("Sol System",)):
            odd.append((i+1, l[:150])); continue
        if name in recs and recs[name] != sector: odd.append((i+1, "sector clash " + name))
        recs[name] = sector
    else:
        odd.append((i+1, l[:150]))
recs.pop("Unknown", None)
names = sorted(recs, key=lambda s: unicodedata.normalize("NFKD", s).lower())
open("planets_for_dropdown.txt", "w", encoding="utf-8", newline="\n").write("\n".join(names) + "\n")
open("planets_and_sectors.tsv", "w", encoding="utf-8", newline="\n").write("Planet\tSector\n" + "".join(f"{n}\t{recs[n]}\n" for n in names))
print(len(names), "planets"); print("odd lines:"); [print(" ", o) for o in odd]
