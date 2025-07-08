#!/usr/bin/env python3
"""
Dynamic OAuth token refresher for GoHighLevel / LeadConnector.

• Reads the current refresh-token and metadata from `tokens.json` in the same directory.
• Uses environment variables GHL_CLIENT_ID and GHL_CLIENT_SECRET for credentials.
• Requests a fresh access/refresh token pair and updates `tokens.json`.
• Designed to be invoked every ~12 h via cron.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()  # Load variables from a .env file if present

import jwt  # type: ignore
import requests

# ----------------------------------------------------------------------------
# Configuration & logging
# ----------------------------------------------------------------------------
TOKEN_URL = "https://services.leadconnectorhq.com/oauth/token"
CLIENT_ID = os.getenv("GHL_CLIENT_ID")
CLIENT_SECRET = os.getenv("GHL_CLIENT_SECRET")
USER_TYPE = "Location"  # required by GHL token endpoint

SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_FILE = SCRIPT_DIR / "tokens.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def load_tokens() -> Dict[str, Any]:
    """Return contents of tokens.json or an empty dict if it doesn't exist."""
    if TOKEN_FILE.exists():
        try:
            with TOKEN_FILE.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:  # pragma: no cover
            logger.error("Error reading %s: %s", TOKEN_FILE, exc)
    return {}


def save_tokens(data: Dict[str, Any]) -> None:
    """Persist token data back to tokens.json."""
    try:
        with TOKEN_FILE.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        logger.info("Tokens saved to %s", TOKEN_FILE)
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to write %s: %s", TOKEN_FILE, exc)


# ----------------------------------------------------------------------------
# Core refresh logic
# ----------------------------------------------------------------------------

def refresh_tokens() -> bool:
    """Refresh the access token using the stored refresh-token."""

    if not CLIENT_ID or not CLIENT_SECRET:
        logger.error("GHL_CLIENT_ID and/or GHL_CLIENT_SECRET not set in environment")
        return False

    stored = load_tokens()
    refresh_token = stored.get("refresh_token") or os.getenv("GHL_REFRESH_TOKEN")

    if not refresh_token:
        logger.error("No refresh_token found in tokens.json or GHL_REFRESH_TOKEN env var")
        return False

    payload = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "user_type": USER_TYPE,
    }

    try:
        logger.info("Requesting new tokens from GHL…")
        resp = requests.post(TOKEN_URL, data=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Token refresh request failed: %s", exc)
        return False

    data = resp.json()
    new_access = data.get("access_token")
    new_refresh = data.get("refresh_token", refresh_token)

    if not new_access:
        logger.error("Response did not include an access_token: %s", data)
        return False

    # Decode JWT (header not verified) to get expiry & metadata
    try:
        decoded = jwt.decode(new_access, options={"verify_signature": False})
    except Exception as exc:  # pragma: no cover
        logger.warning("Unable to decode JWT for expiry metadata: %s", exc)
        decoded = {}

    expires_at: datetime = datetime.fromtimestamp(
        decoded.get("exp", (datetime.now() + timedelta(hours=24)).timestamp())
    )

    # Build token payload to persist
    new_tokens: Dict[str, Any] = {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "token_expires_at": expires_at.isoformat(),
        "location_id": decoded.get("authClassId", stored.get("location_id")),
        "company_id": decoded.get("companyId", stored.get("company_id")),
    }

    save_tokens(new_tokens)
    logger.info("Token refreshed successfully; expires at %s", expires_at.isoformat())
    return True


# ----------------------------------------------------------------------------
# Entry-point
# ----------------------------------------------------------------------------

def main() -> None:
    ok = refresh_tokens()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main() 