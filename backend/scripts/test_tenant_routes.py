"""Quick tenant route smoke test for demo@factory.local."""
from __future__ import annotations

import asyncio
import sys

import httpx

BASE = "http://localhost:8000/api/v1"


async def main() -> int:
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            r = await client.get("http://localhost:8000/health")
            print("health", r.status_code)
        except Exception as exc:
            print("health FAIL", type(exc).__name__, exc)
            return 1

        r = await client.post(f"{BASE}/auth/create-demo-user")
        print("create-demo-user", r.status_code, r.text[:300])

        r = await client.post(
            f"{BASE}/auth/login",
            json={"email": "demo@factory.local", "password": "demo1234"},
        )
        print("login", r.status_code)
        if r.status_code != 200:
            print(r.text)
            return 1

        data = r.json()
        token = data["access_token"]
        print(
            "tenant",
            data.get("tenant", {}).get("company_name"),
            "role",
            data.get("user", {}).get("role"),
        )
        headers = {"Authorization": f"Bearer {token}"}

        endpoints = [
            "/crm/pipeline",
            "/content?limit=5",
            "/content-factory/dashboard",
            "/export-growth/summary",
            "/growth-center/summary",
            "/customer-success/summary",
            "/clients",
        ]
        failed = 0
        for ep in endpoints:
            try:
                resp = await client.get(f"{BASE}{ep}", headers=headers)
                body = resp.text[:150].replace("\n", " ")
                print(f"{ep} -> {resp.status_code} {body}")
                if resp.status_code >= 400:
                    print("  FULL:", resp.text[:3000])
                    failed += 1
            except Exception as exc:
                failed += 1
                print(f"{ep} -> ERROR {type(exc).__name__}: {exc}")

        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
