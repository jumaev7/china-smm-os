# Frontend Dev Environment

This project serves the Next.js frontend on **http://localhost:3000** via **Docker Compose only**. A polluted host `frontend/.next` directory or a local `node.exe` process on port 3000 can cause the browser to receive HTML while CSS/JS chunks return 404 — the page looks like unstyled raw HTML.

## Golden rules

1. **Use Docker frontend as the only source for localhost:3000**
   - Start the stack: `docker compose up -d`
   - Frontend runs inside the `frontend` service with a named Docker volume for `/app/.next`.

2. **Do not run `npm run dev` locally on port 3000 while Docker is used**
   - Local Next dev binds the same port and serves stale or mismatched assets.

3. **Do not run `npm run build` locally while using Docker dev mode**
   - A host `frontend/.next` from a local build can confuse tooling and future local runs. Production builds belong in CI or a one-off Docker run.

4. **If raw HTML / missing styles appear, reset the environment**
   ```powershell
   .\scripts\dev_frontend_reset.ps1
   ```
   This script stops any `node.exe` on port 3000, removes host `frontend/.next`, recreates the Docker frontend container, and runs `scripts/verify_frontend_css.py`.

## Check who owns port 3000

```powershell
.\scripts\check_frontend_port.ps1
```

| Exit code | Meaning |
|-----------|---------|
| 0 | Docker owns port 3000 (expected) |
| 1 | `node.exe` owns port 3000 (conflict — run reset script) |
| 2 | Port free or owned by another process |

## Verify CSS/JS manually

```powershell
python scripts/verify_frontend_css.py
```

Open **/dashboard** and **/tenants** in the browser; Network tab should show `/_next/static/css/...` and `/_next/static/chunks/...` returning **200**.

## Why host `.next` is ignored

`frontend/.next` is listed in `.gitignore`. The Docker named volume `frontend_next_cache` holds the container cache; host `.next` should not exist during normal Docker-based development.

## Production build check (without polluting host)

Run a one-off build inside Docker with a **separate** `.next` volume so the dev cache is not overwritten:

```powershell
docker compose run --rm --no-deps -v frontend_build_check:/app/.next frontend npm run build
```

If you already ran `npm run build` against the dev volume, run `.\scripts\dev_frontend_reset.ps1` to restore dev mode.
