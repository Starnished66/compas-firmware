#!/usr/bin/env bash
# Run every test that works on a clean clone. COMPAS_PLAYER_DIR must point at a compas-player checkout.
# Not run: scripts/tests/disabled (see its README) and the two verification tools that need a kernel
# source tree argument (test_uac_safety.py, test_radio_input_safety.py).
set -u
repo=$(cd "$(dirname "$0")/../.." && pwd)
cd "$repo" || exit 1
: "${COMPAS_PLAYER_DIR:?set COMPAS_PLAYER_DIR}"
fail=0
while IFS= read -r t; do
    case $t in
        scripts/tests/disabled/*|*/test_uac_safety.py|*/test_radio_input_safety.py) continue ;;
        *.sh) cmd=(bash "$t") ;;
        *) cmd=(python3 -I "$t") ;;
    esac
    if log=$("${cmd[@]}" 2>&1); then echo "PASS $t"; else echo "FAIL $t"; printf '%s\n' "$log" | tail -40; fail=1; fi
done < <(git ls-files | grep -E '/(test_[^/]*)$|/run_early_splash_boot_test.sh$' | sort)
rm -f qemu_*.core
exit $fail
