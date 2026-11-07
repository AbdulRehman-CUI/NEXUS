"""Offline administrator tool. Stop the API before changing accounts or claiming legacy data."""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from alembic import command
from alembic.config import Config
from nexus.auth import add_user, hash_password
from nexus.config import Settings
from nexus.database import AuthSession, Membership, User, Workspace, database
from nexus.lease import DataLease
from sqlalchemy import delete, select


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--admin", action="store_true")
    parser.add_argument(
        "--claim-legacy",
        action="store_true",
        help="Explicitly assign only currently unowned workspaces.",
    )
    parser.add_argument("--reset-password", action="store_true")
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    lease = DataLease(settings.data_dir)
    lease.__enter__()
    engine, sessions = database(settings.data_dir.resolve() / "nexus.sqlite3")
    config = Config(str(Path(__file__).resolve().parents[1] / "apps/api/alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with sessions.begin() as session:
        user = session.scalar(select(User).where(User.username == args.username))
        if args.disable or args.reset_password:
            if user is None:
                parser.error("Account not found.")
            if args.disable:
                user.disabled = True
            else:
                password = getpass.getpass("New password (12–256 characters): ")
                if password != getpass.getpass("Repeat password: "):
                    parser.error("Passwords differ.")
                user.password_hash = hash_password(password)
            session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        elif user is not None and args.claim_legacy:
            if not user.admin:
                parser.error(
                    "Only an existing administrator may claim legacy workspaces."
                )
        else:
            password = getpass.getpass("Password (12–256 characters): ")
            if password != getpass.getpass("Repeat password: "):
                parser.error("Passwords differ.")
            user = add_user(session, args.username, password, args.admin)
        if args.claim_legacy:
            if not user.admin:
                parser.error("Only an administrator may claim legacy workspaces.")
            for workspace in session.scalars(
                select(Workspace).where(
                    ~select(Membership.workspace_id)
                    .where(Membership.workspace_id == Workspace.id)
                    .exists()
                )
            ):
                session.add(
                    Membership(workspace_id=workspace.id, user_id=user.id, role="owner")
                )
    engine.dispose()
    lease.__exit__()
    print("Account updated. Passwords and session tokens were not printed.")


if __name__ == "__main__":
    main()
