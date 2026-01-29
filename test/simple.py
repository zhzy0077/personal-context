"""Test uvicorn logging - simpler version."""

import logging
import sys
import uvicorn
from fastapi import FastAPI

LOG_FORMAT = "[%(asctime)s] %(levelname)-8s %(message)s"
DATE_FORMAT = "%m/%d/%y %H:%M:%S"

# Custom log config for uvicorn
UVICORN_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT},
        "access": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT},
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler", 
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
    },
}

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}


if __name__ == "__main__":
    # Configure our own logging first
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    
    logging.info("Starting test server...")
    
    # Pass log_config to uvicorn.run() - this is the key!
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8002,
        log_config=UVICORN_LOG_CONFIG,
    )
