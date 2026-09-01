"""Embed JSON data into index.html for local browser testing (no HTTP server needed)."""
import json, re, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

with open("data/dealer_outstanding.json", encoding="utf-8") as f:
    dealer = json.load(f)
with open("data/daily_collection.json", encoding="utf-8") as f:
    daily = json.load(f)
with open("data/cohort.json", encoding="utf-8") as f:
    cohort = json.load(f)

with open("index.html", encoding="utf-8") as f:
    html = f.read()

# Embed data as global constants
data_block = (
    "const _DATA={dealer_outstanding:"
    + json.dumps(dealer, separators=(',', ':'))
    + ",daily_collection:"
    + json.dumps(daily, separators=(',', ':'))
    + ",cohort:"
    + json.dumps(cohort, separators=(',', ':'))
    + "};\n"
)

# Replace the jf() fetch function with a lookup against embedded data
old_jf = "async function jf(p){try{const r=await fetch(p);return r.ok?r.json():null;}catch{return null;}}"
new_jf = data_block + "async function jf(p){const k=p.replace('data/','').replace('.json','');return _DATA[k]||null;}"

if old_jf not in html:
    print("ERROR: could not find jf() function to replace - check index.html")
    exit(1)

html = html.replace(old_jf, new_jf, 1)

with open("local.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"local.html written ({os.path.getsize('local.html')//1024} KB)")
print(f"  dealer_outstanding: {len(dealer)} rows")
print(f"  daily_collection:   {len(daily)} rows")
print(f"  cohort:             {len(cohort)} rows")
