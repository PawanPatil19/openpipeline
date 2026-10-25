"""ASGI entry point for ``uvicorn openpipeline.app:app`` (used by --reload and Docker)."""

import os

from openpipeline.api import create_app
from openpipeline.security import settings_from_env

_host, _port, _writes = settings_from_env()
app = create_app(
    os.environ.get("OPENPIPELINE_PROJECT_DIR", "."),
    sample_data=os.environ.get("OPENPIPELINE_SAMPLE_DATA"),
    dialect=os.environ.get("OPENPIPELINE_DIALECT"),
    writes=_writes.mode,
    write_token=_writes.token,
    host=_host,
    port=_port,
)
