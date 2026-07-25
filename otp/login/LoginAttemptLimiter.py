"""Small bounded sliding-window limiter for account authentication."""

import time


class LoginAttemptLimiter:
    def __init__(self, maximumAttempts=5, windowSeconds=60.0,
                 maximumKeys=10000):
        self.maximumAttempts = maximumAttempts
        self.windowSeconds = windowSeconds
        self.maximumKeys = maximumKeys
        self.attempts = {}

    def _current(self, key, now):
        return [
            attempt for attempt in self.attempts.get(key, ())
            if now - attempt < self.windowSeconds
        ]

    def _prune(self, now):
        for key in list(self.attempts):
            current = self._current(key, now)
            if current:
                self.attempts[key] = current
            else:
                del self.attempts[key]
        overflow = len(self.attempts) - self.maximumKeys
        if overflow > 0:
            oldest = sorted(
                self.attempts,
                key=lambda key: self.attempts[key][-1])
            for key in oldest[:overflow]:
                del self.attempts[key]

    def consume(self, key, now=None):
        now = time.monotonic() if now is None else now
        current = self._current(key, now)
        if len(current) >= self.maximumAttempts:
            self.attempts[key] = current
            return False
        current.append(now)
        self.attempts[key] = current
        if len(self.attempts) > self.maximumKeys:
            self._prune(now)
        return True

    def reset(self, key):
        self.attempts.pop(key, None)
