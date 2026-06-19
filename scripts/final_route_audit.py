import json, urllib.request, urllib.error, time

BASE = "http://localhost:8000/api/v1"

def login(path, email, pw):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps({"email": email, "password": pw}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["access_token"]

def probe(path, token, timeout=15):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {token}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, int((time.time()-t0)*1000), "ok"
    except urllib.error.HTTPError as e:
        return e.code, int((time.time()-t0)*1000), e.read()[:60].decode()
    except Exception as e:
        return 0, int((time.time()-t0)*1000), str(e)[:60]

routes = [
    ("/dashboard", "/dashboard/overview"),
    ("/executive-copilot", "/executive-copilot/overview"),
    ("/deal-room", "/deal-room/v2/overview"),
    ("/deal-risk", "/deal-risk/overview"),
    ("/revenue-forecast", "/revenue-forecast/overview"),
    ("/revenue-analytics", "/analytics/overview"),
    ("/briefs", "/client-briefs"),
    ("/content", "/content"),
    ("/tasks", "/tasks"),
    ("/calendar", "/calendar/month/2026/6"),
    ("/marketplace", "/marketplace/overview"),
    ("/buyer-search", "/buyer-discovery/overview"),
    ("/buyer-network", "/buyer-network/overview"),
]

tenant = login("/auth/login", "demo@factory.local", "demo1234")
admin = login("/admin-auth/login", "admin@example.com", "ChangeMe_12345!")

for label, token, denied in [
    ("TENANT demo@factory.local", tenant, {"/revenue-forecast"}),
    ("ADMIN admin@example.com", admin, set()),
]:
    print(f"\n=== {label} ===")
    for route, api in routes:
        code, ms, msg = probe(api, token, timeout=12 if "executive" in api else 15)
        if route in denied:
            ok = code in (401, 403)
            result = "PASS (RBAC deny)" if ok else f"FAIL ({code})"
        elif code == 504 or (code == 0 and "timed out" in msg):
            result = "FAIL (timeout)"
        elif 200 <= code < 400:
            result = "PASS"
        else:
            result = f"FAIL ({code})"
        print(f"  {route:22} {result:22} {ms:5}ms  {msg[:40]}")
