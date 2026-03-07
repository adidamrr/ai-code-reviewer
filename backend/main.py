from __future__ import annotations

import uvicorn

from app.config import load_config


if __name__ == "__main__":
    config = load_config()
    uvicorn.run("app.main:app", host="0.0.0.0", port=config.port, reload=False)
