import json
import os
import tempfile
import unittest

from otp.login.PasswordCredentialDB import PasswordCredentialDB


class PasswordCredentialDBTest(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temporary.name, 'credentials.json')
        self.database = PasswordCredentialDB(self.path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_salted_hash_round_trip_never_persists_password(self):
        password = 'correct horse battery staple'
        self.database.setPassword('example-user', password)

        self.assertTrue(self.database.verifyPassword('example-user', password))
        self.assertFalse(self.database.verifyPassword('example-user', 'wrong password'))
        with open(self.path, 'r', encoding='utf-8') as stream:
            stored = stream.read()
        self.assertNotIn(password, stored)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_new_accounts_register_but_legacy_accounts_stay_locked(self):
        authenticated, registered = self.database.authenticateOrRegister(
            'new-account', 'eight-or-more', accountExists=False)
        self.assertTrue(authenticated)
        self.assertTrue(registered)

        authenticated, registered = self.database.authenticateOrRegister(
            'legacy-account', 'eight-or-more', accountExists=True)
        self.assertFalse(authenticated)
        self.assertFalse(registered)
        self.assertFalse(self.database.hasCredential('legacy-account'))

    def test_registration_rejects_short_passwords_and_unsafe_names(self):
        self.assertEqual(
            self.database.authenticateOrRegister(
                'valid-name', 'short', accountExists=False),
            (False, False))
        self.assertEqual(
            self.database.authenticateOrRegister(
                '../unsafe', 'a secure password', accountExists=False),
            (False, False))
        self.assertFalse(os.path.exists(self.path))

    def test_registration_never_overwrites_existing_username(self):
        self.assertTrue(self.database.registerPassword(
            'Existing-Account', 'original password'))
        self.assertFalse(self.database.registerPassword(
            'existing-account', 'replacement password'))
        self.assertTrue(self.database.verifyPassword(
            'EXISTING-ACCOUNT', 'original password'))
        self.assertFalse(self.database.verifyPassword(
            'existing-account', 'replacement password'))

    def test_unknown_or_malformed_hashes_fail_closed(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as stream:
            json.dump({
                'version': 1,
                'accounts': {
                    'broken-account': {
                        'algorithm': 'unknown',
                        'salt': 'not-a-valid-salt',
                        'hash': 'not-a-valid-hash',
                    },
                },
            }, stream)
        database = PasswordCredentialDB(self.path)
        self.assertFalse(database.verifyPassword(
            'broken-account', 'a secure password'))


if __name__ == '__main__':
    unittest.main()
