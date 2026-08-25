#!/usr/bin/env bash
# Prepares demo-repo so cli.py has something real to diff against.
#
# cli.py compares HEAD (a committed baseline) to the working tree. demo-repo
# ships with the "after" state of the demo change already in place, so this
# script:
#   1. inits a throwaway git repo inside demo-repo (if one doesn't exist yet)
#   2. temporarily reverts Customer.email to the "before" type (String)
#   3. commits that as the baseline (HEAD)
#   4. restores the "after" type (Optional<String>) in the working tree
#
# Result: `git -C demo-repo diff HEAD` shows exactly the documented change
# (Customer.email : String -> Optional<String>), which is what cli.py and
# eval.py expect.
set -euo pipefail

cd "$(dirname "$0")"

if [ -d demo-repo/.git ]; then
  echo "demo-repo is already a git repo — nothing to do."
  echo "(delete demo-repo/.git and rerun this script to reset the baseline)"
  exit 0
fi

CUSTOMER=demo-repo/src/main/java/com/shop/model/Customer.java
cp "$CUSTOMER" /tmp/customer_after.java.bak

# Step 2: revert to the "before" type for the baseline commit.
sed -i.bak \
  -e 's/private Optional<String> email;/private String email;/' \
  -e 's/public Optional<String> getEmail()/public String getEmail()/' \
  -e 's/public void setEmail(Optional<String> email)/public void setEmail(String email)/' \
  "$CUSTOMER"
rm -f "$CUSTOMER.bak"

# Step 3: commit the baseline.
git -C demo-repo init -q
git -C demo-repo config user.email "poc@example.com"
git -C demo-repo config user.name "PoC"
git -C demo-repo add -A
git -C demo-repo commit -q -m "baseline: Customer.email as String"

# Step 4: restore the "after" state in the working tree.
cp /tmp/customer_after.java.bak "$CUSTOMER"
rm -f /tmp/customer_after.java.bak

echo "demo-repo initialized. Baseline committed, change is in the working tree."
echo "Run: python cli.py --repo demo-repo --pr \"PR #1842\" --json impact-report.json"
