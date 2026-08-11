import json
from collections import Counter

with open("conexoes.json", "r", encoding="utf-8") as f:
    data = json.load(f)

users = []
no_user_details = []

for op in data.get("inprog", []):
    effective = op.get("effectiveUsers", [])
    if effective:
        users.append(effective[0].get("user", "unknown"))
    else:
        client = op.get("client", "?")
        app = op.get("appName", "")
        desc = op.get("desc", "")
        meta = op.get("clientMetadata", {})
        driver = meta.get("driver", {}).get("name", "") if meta else ""
        label = app or driver or desc or client
        users.append(f"(sem usuario) {label}")
        no_user_details.append({
            "client": client,
            "appName": app,
            "desc": desc,
            "driver": driver,
        })

counter = Counter(users)

print(f"{'Usuário':<70} {'Conexões':>10}")
print("-" * 82)
for user, count in counter.most_common():
    print(f"{user:<70} {count:>10}")

print("-" * 82)
print(f"{'TOTAL':<70} {sum(counter.values()):>10}")

if no_user_details:
    print(f"\n\n--- Detalhes conexões sem usuario ({len(no_user_details)}) ---\n")
    for d in no_user_details[:30]:
        print(f"  client={d['client']}  app={d['appName']}  desc={d['desc']}  driver={d['driver']}")
