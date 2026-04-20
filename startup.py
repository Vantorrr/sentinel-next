#!/usr/bin/env python3
"""
Sentinel-Next — One-Button Launcher

Выполняет:
  1. Проверку .env на наличие обязательных переменных
  2. Проверку доступности PostgreSQL, Redis, Qdrant
  3. Запуск Alembic миграций
  4. Параллельный запуск Backend (uvicorn) и Frontend (npm run dev / node server.js)

Использование:
  python startup.py              # dev mode
  python startup.py --prod       # production (Next.js build output)
  python startup.py --backend-only
  python startup.py --frontend-only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Colour helpers ────────────────────────────────────────────────────────────

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

OK    = _c("✅", "92")
FAIL  = _c("❌", "91")
WARN  = _c("⚠ ", "93")
INFO  = _c("ℹ ", "96")
BOLD  = lambda t: _c(t, "1")  # noqa: E731

def banner() -> None:
    print()
    print(_c("  ╔══════════════════════════════════╗", "36"))
    print(_c("  ║   SENTINEL-NEXT  v2026           ║", "36"))
    print(_c("  ║   AI Business Intelligence       ║", "36"))
    print(_c("  ╚══════════════════════════════════╝", "36"))
    print()

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
ENV_FILE = ROOT / ".env"

# ── 1. Env validation ─────────────────────────────────────────────────────────

REQUIRED_VARS = ["SECRET_KEY", "DATABASE_URL", "REDIS_URL", "QDRANT_URL"]
RECOMMENDED_VARS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]


def check_env() -> bool:
    print(BOLD("1. Checking .env …"))

    if not ENV_FILE.exists():
        print(f"  {WARN} .env not found — copying from .env.example")
        example = ROOT / ".env.example"
        if example.exists():
            import shutil
            shutil.copy(example, ENV_FILE)
            print(f"  {INFO} Created .env — please fill in real values")
        else:
            print(f"  {FAIL} No .env.example either. Aborting.")
            return False

    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE, override=False)
    except ImportError:
        # Fallback if python-dotenv not installed
        with ENV_FILE.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    missing = [k for k in REQUIRED_VARS if not os.environ.get(k)]
    if missing:
        print(f"  {FAIL} Missing required env vars: {', '.join(missing)}")
        return False
    print(f"  {OK} Required vars present")

    secret = os.environ.get("SECRET_KEY", "")
    if "change-me" in secret or len(secret) < 16:
        print(f"  {FAIL} SECRET_KEY is default/weak! Generate a real one:")
        print('       python -c "import secrets; print(secrets.token_hex(32))"')
        return False
    print(f"  {OK} SECRET_KEY is configured")

    no_llm = all(not os.environ.get(k) for k in RECOMMENDED_VARS)
    if no_llm:
        print(f"  {WARN} No LLM API key set — narrative summaries will use rule-based fallback")
    else:
        print(f"  {OK} LLM key configured")

    return True


# ── 2. Service connectivity ───────────────────────────────────────────────────

async def _ping_postgres(url: str) -> bool:
    try:
        import asyncpg
        conn = await asyncio.wait_for(asyncpg.connect(url.replace("+asyncpg", "")), timeout=5)
        await conn.close()
        return True
    except Exception as exc:
        print(f"  {FAIL} PostgreSQL: {exc}")
        return False


async def _ping_redis(url: str) -> bool:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(url, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        return True
    except Exception as exc:
        print(f"  {FAIL} Redis: {exc}")
        return False


async def _ping_qdrant(url: str) -> bool:
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(url + "/", timeout=aiohttp.ClientTimeout(total=3)) as r:
                return r.status == 200
    except Exception as exc:
        print(f"  {FAIL} Qdrant: {exc}")
        return False


async def check_services() -> bool:
    print(BOLD("2. Checking infrastructure services …"))
    db_url   = os.environ.get("DATABASE_URL", "")
    redis_url = os.environ.get("REDIS_URL", "")
    qdrant_url = os.environ.get("QDRANT_URL", "")

    ok_db, ok_redis, ok_qdrant = await asyncio.gather(
        _ping_postgres(db_url),
        _ping_redis(redis_url),
        _ping_qdrant(qdrant_url),
    )

    if ok_db:   print(f"  {OK} PostgreSQL reachable")
    if ok_redis: print(f"  {OK} Redis reachable")
    if ok_qdrant: print(f"  {OK} Qdrant reachable")

    if not (ok_db and ok_redis):
        print(f"\n  {WARN} Critical services missing. Start them first:")
        print("       docker compose up postgres redis qdrant -d")
        return False
    return True


# ── 3. DB Migrations ──────────────────────────────────────────────────────────

def run_migrations() -> bool:
    print(BOLD("3. Running Alembic migrations …"))
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  {FAIL} Migration failed:\n{result.stderr}")
        return False
    print(f"  {OK} Database schema up to date")
    return True


# ── 4. Launch processes ───────────────────────────────────────────────────────

def launch_backend() -> subprocess.Popen:  # type: ignore[type-arg]
    print(f"  {INFO} Starting backend on :8000 …")
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "sentinel.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload",
            "--reload-dir", str(BACKEND_DIR / "sentinel"),
        ],
        cwd=BACKEND_DIR,
    )


def launch_frontend(prod: bool = False) -> subprocess.Popen:  # type: ignore[type-arg]
    print(f"  {INFO} Starting frontend on :3000 …")
    if prod and (FRONTEND_DIR / ".next" / "standalone").exists():
        cmd = ["node", str(FRONTEND_DIR / ".next" / "standalone" / "server.js")]
    else:
        cmd = ["npm", "run", "dev"]
    return subprocess.Popen(cmd, cwd=FRONTEND_DIR)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Sentinel-Next launcher")
    parser.add_argument("--prod", action="store_true", help="Production mode (no hot-reload)")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--skip-checks", action="store_true", help="Skip service connectivity checks")
    parser.add_argument("--skip-migrate", action="store_true", help="Skip Alembic migrations")
    args = parser.parse_args()

    banner()

    # Env check
    if not check_env():
        sys.exit(1)

    # Service checks
    if not args.skip_checks and not args.frontend_only:
        if not asyncio.run(check_services()):
            ans = input("\n  Continue anyway? [y/N] ").strip().lower()
            if ans != "y":
                sys.exit(1)

    # Migrations
    if not args.skip_migrate and not args.frontend_only:
        if not run_migrations():
            sys.exit(1)

    print(BOLD("4. Launching services …"))
    procs: list[subprocess.Popen] = []  # type: ignore[type-arg]

    if not args.frontend_only:
        procs.append(launch_backend())
        time.sleep(2)  # give backend a head start

    if not args.backend_only:
        procs.append(launch_frontend(prod=args.prod))

    print()
    print(_c("  🛡  Sentinel-Next is running!", "92"))
    print(f"  {INFO} Dashboard:  http://localhost:3000")
    print(f"  {INFO} API Docs:   http://localhost:8000/docs")
    print(f"  {INFO} Demo mode:  http://localhost:3000?demo=1")
    print(f"  {INFO} Auth:       Используйте SECRET_KEY как API ключ для входа")
    print()
    print("  Press Ctrl+C to stop all services.")
    print()

    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\n\n  Stopping Sentinel-Next…")
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        print("  Goodbye.")


if __name__ == "__main__":
    main()
