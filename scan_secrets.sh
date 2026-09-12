#!/bin/sh
# Fails if anything staged/tracked looks like a real credential or a
# hardcoded internal host. Run before committing:  ./scan_secrets.sh
# ponytail: grep-based, not entropy-based. Swap in gitleaks if this misses one.
cd "$(dirname "$0")" || exit 1
fail=0

report() { echo "$1"; shift; printf '%s\n' "$@" | sed 's/^/    /'; fail=1; }

# 1. Config files that must never be tracked.
bad=$(git ls-files | grep -E '(^|/)(\.env|db_config\.json)$|\.(db|sqlite3?)$')
[ -n "$bad" ] && report "TRACKED CONFIG/DB FILES:" "$bad"

# 2. Live provider keys and private keys.
keys=$(git grep -nIE 'sk_live_[A-Za-z0-9]|pk_live_[A-Za-z0-9]|rk_live_|gh[pousr]_[A-Za-z0-9]{10}|AKIA[0-9A-Z]{12}|xox[baprs]-[0-9]|-----BEGIN [A-Z ]*PRIVATE KEY' -- . ':!scan_secrets.sh' 2>/dev/null)
[ -n "$keys" ] && report "LIVE KEYS / PRIVATE KEYS:" "$keys"

# 3. Passwords assigned a literal default instead of read from the environment.
pw=$(git grep -nIE "(password|passwd|secret|api_key|token)[A-Za-z_]*['\"]?[[:space:]]*[:=][[:space:]]*['\"][^'\"]{4,}['\"]" -- '*.py' '*.sh' '*.yml' '*.yaml' '*.json' ':!scan_secrets.sh' 2>/dev/null \
  | grep -viE "request\.|\.get\(|os\.environ|getenv|config\[|kwargs|\\\$\{|\\\$\(|VARCHAR|TEXT |INSERT|SELECT|hash|form\[")
[ -n "$pw" ] && report "HARDCODED SECRET DEFAULTS:" "$pw"

# 4. Hardcoded internal/company hosts in code (docs and .example are fine).
hosts=$(git grep -nIE 'https?://[A-Za-z0-9.-]*(sondela|halopsa|psaconsultant|autotask)[A-Za-z0-9.-]*' -- '*.py' '*.sh' '*.yml' '*.yaml' ':!scan_secrets.sh' 2>/dev/null \
  | grep -viE 'os\.environ|getenv|\.example|#')
[ -n "$hosts" ] && report "HARDCODED INTERNAL HOSTS (move to env):" "$hosts"

[ "$fail" = 0 ] && echo "clean: no secrets, weak defaults or hardcoded hosts tracked"
exit "$fail"
