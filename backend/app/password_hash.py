"""Generate a password hash interactively; never accept passwords in arguments."""

import getpass

from .auth import hash_password


def main() -> None:
    password = getpass.getpass("Password (at least 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12 or len(password) > 1024:
        raise SystemExit("Password must contain 12 to 1024 characters.")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    print(hash_password(password))


if __name__ == "__main__":
    main()
