"""Create an external credential file using interactive, hidden password prompts."""

import argparse
import getpass
import os
import sys
import warnings
from pathlib import Path

import yaml

from .auth import hash_password


def collect_users() -> list[dict[str, str]]:
    users: list[dict[str, str]] = []
    for index in range(3):
        username = input(
            f"Username for account {index + 1}"
            + (" (Enter to finish)" if users else "")
            + ": "
        )
        if username == "" and users:
            break
        if not username.strip() or username != username.strip() or len(username) > 64:
            raise ValueError("Username must be 1-64 characters without surrounding whitespace.")
        if any(user["username"] == username for user in users):
            raise ValueError("Usernames must be unique.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass(f"Password for {username} (12-1024 characters): ")
            confirmation = getpass.getpass("Confirm password: ")
        if not 12 <= len(password) <= 1024:
            raise ValueError("Password must contain 12 to 1024 characters.")
        if password != confirmation:
            raise ValueError("Passwords do not match.")
        users.append({"username": username, "password_hash": hash_password(password)})
    return users


def write_credentials(path: Path, users: list[dict[str, str]]) -> None:
    """Create with restrictive permissions; never replace an existing file."""
    content = yaml.safe_dump({"users": users}, sort_keys=False)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
    except OSError:
        path.unlink()
        raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new external auth-users.yaml path")
    args = parser.parse_args(argv)
    path = args.output.absolute()
    if path.exists() or path.is_symlink():
        parser.error(f"{path} already exists; refusing to overwrite credentials")
    if not path.parent.is_dir():
        parser.error(f"Configuration directory does not exist: {path.parent}")
    if not sys.stdin.isatty():
        parser.error("Interactive terminal required. For Docker, use docker run --rm -it.")
    try:
        users = collect_users()
        write_credentials(path, users)
    except (OSError, ValueError, EOFError, getpass.GetPassWarning) as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        raise SystemExit("Account setup cancelled; no credentials were saved.") from None
    print(f"Created {path} with {len(users)} account(s), owner-only permissions.")
    print("Configure auth.credentials_file and auth.origins, then restart the backend.")


if __name__ == "__main__":
    main()
