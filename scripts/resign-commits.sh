#!/usr/bin/env bash
# Re-sign all commits from root using SSH signing (YubiKey FIDO2).
# Pauses between each commit for YubiKey touch.
set -e

TOTAL=$(git rev-list --count HEAD)
echo "Will re-sign $TOTAL commits with YubiKey SSH key."
echo "Touch your YubiKey when it blinks for EACH commit."
echo ""

GIT_SEQUENCE_EDITOR="sed -i 's/^pick /edit /'" git rebase --root

COUNT=0
while true; do
    COUNT=$((COUNT + 1))
    SUBJECT=$(git log -1 --format='%s' HEAD)
    echo ""
    echo "=== Signing commit $COUNT/$TOTAL: $SUBJECT ==="
    echo ">>> Touch your YubiKey now! <<<"
    git commit --amend --no-edit -S

    if ! git rebase --continue 2>/dev/null; then
        break
    fi
done

echo ""
echo "All $TOTAL commits signed!"
git log --format='%h %G? %s' --all
