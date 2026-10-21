"""Start the approved persistent release under Render's existing service identity.

Used with the pinned official Python image when Git deployment is unavailable.
Dependencies are prepared in packages/ before deploying; startup never installs code.
"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if os.geteuid() == 0:
    os.setgroups([])
    os.setgid(1000)
    os.setuid(1000)
if os.geteuid() != 1000:
    raise RuntimeError("Unexpected service identity")
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), str(ROOT / "packages")]
sys.dont_write_bytecode = True

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
                workers=1, proxy_headers=True, access_log=False)
