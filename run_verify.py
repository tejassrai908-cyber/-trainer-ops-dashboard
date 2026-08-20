#!/usr/bin/env python3
"""Launcher used ONLY by `hermes verify`.

The verify harness launches the start command from a working directory we
cannot predict, so we point at an ABSOLUTE path to app.py. We also respect the
PORT environment variable (the harness passes its own port here) falling back
to 5000, so the readiness poll hits the right port. Dependencies (flask,
gunicorn) are already installed in the project venv, so no bootstrap is needed.
"""
import os
import sys

PORT = os.environ.get("PORT", "5000")
sys.path.insert(0, r"C:\Users\tejas\trainer-ops-local")
os.chdir(r"C:\Users\tejas\trainer-ops-local")

import app as _app  # noqa: E402

if __name__ == "__main__":
    _app.app.run(host="0.0.0.0", port=int(PORT), debug=False)
