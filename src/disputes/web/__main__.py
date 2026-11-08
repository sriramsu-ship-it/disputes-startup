"""`python -m disputes.web` runs the workbench and client portal on http://127.0.0.1:8000 (synthetic)."""
from __future__ import annotations

import logging

import uvicorn

from disputes.web.app import create_app
from disputes.web.pii import install_log_masking


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    install_log_masking()
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_config=None)


if __name__ == "__main__":
    main()
