"""CLI to bootstrap an admin user for a ConvocaRadar organization.

Usage:
    convocaradar-seed-admin --email admin@example.com --password-env ADMIN_PW
    convocaradar-seed-admin --email admin@example.com --password-env ADMIN_PW --org my-org-slug --force
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Organization, Role, User


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap an admin user for a ConvocaRadar organization",
    )
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument(
        "--password-env",
        required=True,
        help="Name of environment variable containing the password",
    )
    parser.add_argument(
        "--org",
        default=None,
        help="Organization slug (default: first organization found)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Create admin even if one already exists in the org",
    )

    args = parser.parse_args()

    password = os.environ.get(args.password_env)
    if not password:
        print(
            f"ERROR: Environment variable '{args.password_env}' is not set or is empty",
            file=sys.stderr,
        )
        sys.exit(1)

    db = SessionLocal()
    try:
        # Resolve organization
        if args.org:
            org = db.scalar(select(Organization).where(Organization.slug == args.org))
            if not org:
                print(f"ERROR: Organization with slug '{args.org}' not found", file=sys.stderr)
                sys.exit(1)
        else:
            org = db.scalars(select(Organization).limit(1)).first()
            if not org:
                print("ERROR: No organizations found in the database", file=sys.stderr)
                sys.exit(1)

        # Safety check: refuse to create a second admin unless --force
        if not args.force:
            existing_admin = db.scalar(
                select(User).where(
                    User.organization_id == org.id,
                    User.role == Role.admin.value,
                ).limit(1),
            )
            if existing_admin:
                print(
                    f"ERROR: An admin user already exists for org '{org.slug}'. "
                    "Use --force to create another.",
                    file=sys.stderr,
                )
                sys.exit(1)

        user = User(
            email=args.email,
            name=f"Admin {args.email.split('@')[0]}",
            password_hash=hash_password(password),
            role=Role.admin.value,
            organization_id=org.id,
        )
        db.add(user)
        db.commit()
        print(f"Admin user '{args.email}' created successfully in org '{org.slug}'")
        sys.exit(0)
    finally:
        db.close()


if __name__ == "__main__":
    main()
