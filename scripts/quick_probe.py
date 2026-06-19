import json, urllib.request, urllib.error, time

BASE = "http://localhost:8000/api/v1"

def login(path, email, pw):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps({"email": email, "password": pw}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["access_token"]

def probe(path, token, timeout=25):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {token}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, int((time.time()-t0)*1000), "ok"
    except urllib.error.HTTPError as e:
        return e.code, int((time.time()-t0)*1000), e.read()[:80].decode()
    except Exception as e:
        return 0, int((time.time()-t0)*1000), str(e)[:80]

apis = [
    "/dashboard/overview",
    "/executive-copilot/overview",
    "/deal-room/v2/overview",
    "/deal-risk/overview",
    "/revenue-forecast/overview",
    "/analytics/overview",
    "/client-briefs",
    "/content",
    "/tasks",
    "/calendar",
    "/marketplace/overview",
    "/buyer-discovery/overview",
    "/buyer-network/overview",
    "/pilot-readiness/overview",
]

tenant = login("/auth/login", "demo@factory.local", "demo1234")
admin = login("/admin-auth/login", "admin@example.com", "ChangeMe_12345!")

for label, token in [("TENANT", tenant), ("ADMIN", admin)]:
    print(f"\n=== {label} ===")
    for api in apis:
        code, ms, msg = probe(api, token)
        print(f"  {code:3} {ms:5}ms  {api}  {msg[:60]}")
