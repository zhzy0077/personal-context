"""Test FastAPI app to figure out uvicorn logging configuration."""

import logging
import sys

from fastapi import FastAPI

# Custom logging format
LOG_FORMAT = "[%(asctime)s] %(levelname)-8s %(message)s"
DATE_FORMAT = "%m/%d/%y %H:%M:%S"


def configure_logging():
    """Configure unified logging format."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    
    # Try to configure uvicorn loggers
    for name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False


app = FastAPI()


@app.get("/")
async def root():
    logging.info("Root endpoint called")
    return {"message": "Hello World"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    
    configure_logging()
    
    # Try different approaches:
    
    # Approach 1: Pass log_config=None to disable uvicorn's logging config
    # uvicorn.run(app, host="0.0.0.0", port=8002, log_config=None)
    
    # Approach 2: Pass custom log_config dict
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": LOG_FORMAT,
                "datefmt": DATE_FORMAT,
            },
            "access": {
                "format": LOG_FORMAT,
                "datefmt": DATE_FORMAT,
            },
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
    
    logging.info("Starting test server on http://0.0.0.0:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002, log_config=log_config)
