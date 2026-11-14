#!/bin/sh
# Vercel runs this before each build, from frontend/: exit 0 skips the build, exit 1 builds.
#
# It compares frontend/ with the commit Vercel last deployed for this branch, not just with the
# previous commit. So a pull request that changed the page in an earlier commit still gets a
# preview, and a merge to main builds whatever changed since production. With nothing to
# compare with, it builds.
previous="${VERCEL_GIT_PREVIOUS_SHA:-}"

if [ -z "$previous" ] || ! git cat-file -e "${previous}^{commit}" 2>/dev/null; then
  echo "No earlier deployment to compare with, so building."
  exit 1
fi

if git diff --quiet "$previous" HEAD -- .; then
  echo "Nothing in frontend/ changed since ${previous}, so skipping the build."
  exit 0
fi

echo "frontend/ changed since ${previous}, so building."
exit 1
