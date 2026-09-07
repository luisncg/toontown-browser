#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

npm run test:password-auth
npm run test:login-rate-limit
npm run test:game-authority
npm run test:game-authority-python
npm run test:game-authority-manager
npm run test:game-authority-ledger
npm run test:security-authority-guards
npm run test:dc-schema-compatibility
npm run test:estate-transactions
npm run test:bingo-native
npm run test:reactive-native
npm run test:classic-buildings
