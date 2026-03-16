import json

a = json.load(open('log/ant_request_1.json', 'r', encoding='utf-8'))
b = json.load(open('log/ant_request_2.json', 'r', encoding='utf-8'))
c = json.load(open('log/ant_request_3.json', 'r', encoding='utf-8'))

print("=== Request 1 vs 2 ===")
print(f"system identical: {a['system'] == b['system']}")
print(f"messages identical: {a['messages'] == b['messages']}")
print(f"output_config identical: {a.get('output_config') == b.get('output_config')}")
print(f"model identical: {a['model'] == b['model']}")
print(f"max_tokens identical: {a['max_tokens'] == b['max_tokens']}")
print(f"temperature identical: {a['temperature'] == b['temperature']}")

# Check all top-level keys
all_keys = set(a.keys()) | set(b.keys())
for k in sorted(all_keys):
    if a.get(k) != b.get(k):
        print(f"  DIFFERS: {k}")
        if k == 'messages':
            print(f"    req1: {json.dumps(a[k], ensure_ascii=False)[:200]}")
            print(f"    req2: {json.dumps(b[k], ensure_ascii=False)[:200]}")

print("\n=== Request 1 vs 3 ===")
print(f"system identical: {a['system'] == c['system']}")
print(f"messages identical: {a['messages'] == c['messages']}")
print(f"output_config identical: {a.get('output_config') == c.get('output_config')}")

all_keys = set(a.keys()) | set(c.keys())
for k in sorted(all_keys):
    if a.get(k) != c.get(k):
        print(f"  DIFFERS: {k}")
        if k == 'output_config':
            print(f"    req1: {json.dumps(a.get(k), ensure_ascii=False)[:300]}")
            print(f"    req3: {json.dumps(c.get(k), ensure_ascii=False)[:300]}")
