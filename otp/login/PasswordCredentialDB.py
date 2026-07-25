"""Private, file-backed password credentials for the Astron account bridge."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile


USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$')
MINIMUM_PASSWORD_LENGTH = 8
MAXIMUM_PASSWORD_LENGTH = 128
SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LENGTH = 32
SCRYPT_MAX_MEMORY = 64 * 1024 * 1024


def _encode(value):
    return base64.urlsafe_b64encode(value).decode('ascii')


def _decode(value):
    return base64.b64decode(value.encode('ascii'), altchars=b'-_', validate=True)


class PasswordCredentialDB:
    """Store salted scrypt hashes without ever persisting raw passwords."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.records = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, 'r', encoding='utf-8') as stream:
            payload = json.load(stream)
        if payload.get('version') != 1 or not isinstance(
                payload.get('accounts'), dict):
            raise ValueError('unsupported credentials database format')
        self.records = payload['accounts']

    def _save(self):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, mode=0o750, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix='.credentials-', suffix='.tmp', dir=directory, text=True)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(
                    {'version': 1, 'accounts': self.records},
                    stream,
                    indent=2,
                    sort_keys=True)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @staticmethod
    def validateUsername(username):
        return (
            isinstance(username, str)
            and USERNAME_PATTERN.fullmatch(username) is not None
        )

    @staticmethod
    def validatePassword(password, allowWeak=False):
        minimum = 1 if allowWeak else MINIMUM_PASSWORD_LENGTH
        return (
            isinstance(password, str)
            and minimum <= len(password) <= MAXIMUM_PASSWORD_LENGTH
            and '\x00' not in password
        )

    @staticmethod
    def _derive(password, salt):
        return hashlib.scrypt(
            password.encode('utf-8'),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            maxmem=SCRYPT_MAX_MEMORY,
            dklen=SCRYPT_LENGTH)

    def hasCredential(self, username):
        return self._findCredentialUsername(username) is not None

    def _findCredentialUsername(self, username):
        if not isinstance(username, str):
            return None
        if username in self.records:
            return username
        folded = username.casefold()
        for storedUsername in self.records:
            if storedUsername.casefold() == folded:
                return storedUsername
        return None

    def setPassword(self, username, password, allowWeak=False):
        if not self.validateUsername(username):
            raise ValueError('account names must be 3-32 letters, numbers, dots, dashes, or underscores')
        if not self.validatePassword(password, allowWeak=allowWeak):
            raise ValueError(
                'password must be %s-%s characters' % (
                    1 if allowWeak else MINIMUM_PASSWORD_LENGTH,
                    MAXIMUM_PASSWORD_LENGTH))
        salt = secrets.token_bytes(16)
        passwordHash = self._derive(password, salt)
        storedUsername = self._findCredentialUsername(username) or username
        self.records[storedUsername] = {
            'algorithm': 'scrypt',
            'n': SCRYPT_N,
            'r': SCRYPT_R,
            'p': SCRYPT_P,
            'salt': _encode(salt),
            'hash': _encode(passwordHash),
        }
        self._save()

    def verifyPassword(self, username, password):
        storedUsername = self._findCredentialUsername(username)
        record = self.records.get(storedUsername)
        if record is None or not self.validatePassword(password, allowWeak=True):
            return False
        try:
            if (
                record.get('algorithm') != 'scrypt'
                or record.get('n') != SCRYPT_N
                or record.get('r') != SCRYPT_R
                or record.get('p') != SCRYPT_P
            ):
                return False
            salt = _decode(record['salt'])
            expected = _decode(record['hash'])
            actual = self._derive(password, salt)
        except (KeyError, TypeError, ValueError):
            return False
        return hmac.compare_digest(actual, expected)

    def registerPassword(self, username, password):
        """Create credentials without ever overwriting an existing username."""
        if not self.validateUsername(username):
            raise ValueError(
                'account names must be 3-32 letters, numbers, dots, dashes, or underscores')
        if not self.validatePassword(password):
            raise ValueError(
                'password must be %s-%s characters' % (
                    MINIMUM_PASSWORD_LENGTH, MAXIMUM_PASSWORD_LENGTH))
        if self.hasCredential(username):
            return False
        self.setPassword(username, password)
        return True

    def authenticateOrRegister(self, username, password, accountExists):
        """Authenticate an account or establish credentials for a new one."""
        if self.hasCredential(username):
            return self.verifyPassword(username, password), False
        if accountExists:
            # Legacy usernames must be reset locally; never let a public caller
            # claim an existing Toon account merely by being first.
            return False, False
        if not self.validateUsername(username) or not self.validatePassword(password):
            return False, False
        registered = self.registerPassword(username, password)
        return registered, registered
