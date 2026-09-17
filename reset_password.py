#!/usr/bin/env python3
"""Reset a local user's password.

Run it and type the new password when prompted; it is never passed as an
argument, so it does not end up in shell history.

    python reset_password.py christimm
"""
import getpass
import sys

from app_core import get_db, hash_password


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    username = sys.argv[1]

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        if cursor.fetchone() is None:
            print(f"No user called {username!r}.")
            cursor.execute('SELECT username FROM users')
            print("Users:", ', '.join(r[0] for r in cursor.fetchall()) or '(none)')
            return 1

        new = getpass.getpass('New password: ')
        if len(new) < 8:
            print("Too short - use at least 8 characters.")
            return 1
        if new != getpass.getpass('Confirm: '):
            print("They do not match.")
            return 1

        cursor.execute('UPDATE users SET password_hash = ? WHERE username = ?',
                       (hash_password(new), username))
        conn.commit()

    print(f"Password updated for {username}.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
