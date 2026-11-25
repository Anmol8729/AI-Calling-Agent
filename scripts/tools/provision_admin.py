"""Securely provision or rotate credentials for the single designated admin account.

Usage:
    python scripts/tools/provision_admin.py
    INITIAL_ADMIN_PASSWORD="..." python scripts/tools/provision_admin.py --email admin@example.com

Never hardcode admin credentials in source code or commit them to Git.
"""

import argparse
import asyncio
import getpass
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow running from repository root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select
from backend.config.settings import settings
from backend.models import User, Tenant
from backend.schemas.auth import validate_password_strength
from backend.services.auth_service import get_password_hash
from backend.services.db import connect_to_db, close_db_connection, get_sessionmaker


async def provision_admin(email: str, password: str, name: str) -> None:
    await connect_to_db()
    session_factory = get_sessionmaker()
    if session_factory is None:
        print("ERROR: Database is not configured. Check DATABASE_URL / DB_* in .env.")
        sys.exit(1)

    async with session_factory() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        pw_hash = get_password_hash(password)

        if user is None:
            tenant = Tenant(
                name="Clarivo Platform Admin",
                subscription="scale",
                status="active",
            )
            db.add(tenant)
            await db.flush()

            user = User(
                email=email,
                password_hash=pw_hash,
                name=name,
                role="doctor",
                clinic_id=tenant.id,
                is_active=True,
                token_version=1,
                email_verified_at=datetime.utcnow(),
                password_changed_at=datetime.utcnow(),
            )
            db.add(user)
            action = "created"
        else:
            user.password_hash = pw_hash
            user.is_active = True
            user.failed_login_attempts = 0
            user.locked_until = None
            user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
            user.password_changed_at = datetime.utcnow()
            if user.email_verified_at is None:
                user.email_verified_at = datetime.utcnow()
            action = "rotated credentials for"

        await db.commit()
        print(f"Successfully {action} designated admin account: {email} (Argon2id hashed, active sessions rotated).")

    await close_db_connection()


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision or rotate the single Clarivo admin account.")
    parser.add_argument("--email", default="", help="Admin email (defaults to ADMIN_EMAIL / SUPERADMIN_EMAILS)")
    parser.add_argument("--name", default="Platform Administrator", help="Display name for admin account")
    args = parser.parse_args()

    email = (args.email or settings.designated_admin_email or "").strip().lower()
    if not email:
        print("ERROR: Set ADMIN_EMAIL in .env or pass --email.")
        sys.exit(1)

    password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    if not password:
        password = getpass.getpass(f"Enter strong password for {email}: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("ERROR: Passwords do not match.")
            sys.exit(1)

    try:
        validate_password_strength(password)
    except ValueError as e:
        print(f"ERROR: Password does not meet policy: {e}")
        sys.exit(1)

    asyncio.run(provision_admin(email, password, args.name))


if __name__ == "__main__":
    main()
