"""ASGI entry point for ``uvicorn openpipeline.app:app`` (used by --reload and Docker)."""

import os

from openpipeline.api import create_app

app = create_app(os.environ.get("OPENPIPELINE_PROJECT_DIR", "."))
