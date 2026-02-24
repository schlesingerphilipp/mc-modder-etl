import os
import logging

# Configure the logger
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
)
LOGGER = logging.getLogger("modder_mc_service")
LOGGER.setLevel(LOG_LEVEL)