"""The BLB API as a Vercel Python function. deploy/api/vercel.json sends every path here.

The package lives in src/, which Vercel doesn't install, so it is put on the import path. Data
comes from data/, uploaded with each deploy (see scripts/deploy-api.sh). With no STATE_DIR, usage
counts are kept in memory, and each running copy of the function keeps its own.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recommender.api import create_app  # noqa: E402

app = create_app()
