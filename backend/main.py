"""Compatibility entry point for uv run python main.py and existing containers."""

import os
import uvicorn
from app.main import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
