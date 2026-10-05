import json

files = [
    ("Leviticus", "output/topics_leviticus.json"),
    ("Deuteronomy", "output/topics_deuteronomy.json"),
    ("Job", "output/topics_job.json"),
]

for name, path in files:
    d = json.load(open(path, encoding="utf-8"))
    print(f"=== {name} | docs={d['num_documents']} topics={d['num_topics']} ===")
    for t in d["topics"][:4]:
        lbl = t["label"]
        pct = t["doc_share_pct"]
        kw  = " + ".join(t["top_words"][:6])
        print(f"  [{lbl:15s}] {pct:5.1f}% | {kw}")
    print()

p = json.load(open("output/topics_profile.json", encoding="utf-8"))
ratio = p["ritual_vs_ethics_ratio"]
print(f"Ritual/Ethics ratio: {ratio:.1%} ritual")
print("Thematic distribution:")
for book, dist in p["thematic_distribution"].items():
    print(f"  {book}: {dist}")
