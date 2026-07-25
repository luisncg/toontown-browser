import unittest

from otp.login.LoginAttemptLimiter import LoginAttemptLimiter


class LoginAttemptLimiterTests(unittest.TestCase):
    def test_rejects_attempt_over_limit_inside_window(self):
        limiter = LoginAttemptLimiter(maximumAttempts=2, windowSeconds=60)
        self.assertTrue(limiter.consume('account', now=100))
        self.assertTrue(limiter.consume('account', now=101))
        self.assertFalse(limiter.consume('account', now=102))

    def test_window_expiry_allows_another_attempt(self):
        limiter = LoginAttemptLimiter(maximumAttempts=1, windowSeconds=60)
        self.assertTrue(limiter.consume('account', now=100))
        self.assertFalse(limiter.consume('account', now=159.9))
        self.assertTrue(limiter.consume('account', now=160))

    def test_reset_clears_successful_account(self):
        limiter = LoginAttemptLimiter(maximumAttempts=1)
        self.assertTrue(limiter.consume('account', now=100))
        limiter.reset('account')
        self.assertTrue(limiter.consume('account', now=101))

    def test_pruning_removes_expired_keys(self):
        limiter = LoginAttemptLimiter(
            maximumAttempts=1, windowSeconds=5, maximumKeys=1)
        self.assertTrue(limiter.consume('old', now=100))
        self.assertTrue(limiter.consume('new', now=106))
        self.assertNotIn('old', limiter.attempts)


if __name__ == '__main__':
    unittest.main()
