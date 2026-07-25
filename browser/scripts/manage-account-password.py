#!/usr/bin/env python3
"""Set or inspect Toontown password credentials from the private server."""

import argparse
import getpass
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from otp.login.PasswordCredentialDB import PasswordCredentialDB  # noqa: E402


def readPassword(useStdin):
    if useStdin:
        password = sys.stdin.readline().rstrip('\n')
        if not password:
            raise ValueError('password input was empty')
        return password
    first = getpass.getpass('New password: ')
    second = getpass.getpass('Repeat password: ')
    if first != second:
        raise ValueError('passwords did not match')
    return first


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--database',
        default=str(PROJECT_ROOT / 'astron/databases/credentials.json'))
    commands = parser.add_subparsers(dest='command', required=True)

    status = commands.add_parser('status')
    status.add_argument('username')

    setPassword = commands.add_parser('set')
    setPassword.add_argument('username')
    setPassword.add_argument('--password-stdin', action='store_true')
    setPassword.add_argument('--allow-weak', action='store_true')

    args = parser.parse_args()
    credentials = PasswordCredentialDB(args.database)
    if args.command == 'status':
        print('configured' if credentials.hasCredential(args.username) else 'missing')
        return 0 if credentials.hasCredential(args.username) else 1

    password = readPassword(args.password_stdin)
    credentials.setPassword(
        args.username, password, allowWeak=args.allow_weak)
    print('Password credential updated for %s.' % args.username)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print('Error: %s' % error, file=sys.stderr)
        raise SystemExit(2)
