"""Server bootstrap: config loading + logger setup.

Loaded once at process start. The runtime module imports from here.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

# Configure logging first (stderr-only per AGENTS.md rules)
_LOG_LEVEL = os.environ.get("ETSY_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger("etsy_mcp")


def load_config() -> Any:
    """Load the YAML config with env var interpolation.

    Returns an OmegaConf DictConfig. The config file lives at
    `config/config.yaml` relative to this module.
    """
    try:
        from omegaconf import OmegaConf
    except ImportError:
        logger.warning("OmegaConf not installed; returning minimal config from env vars")
        return _fallback_config_from_env()

    config_path = Path(__file__).parent / "config" / "config.yaml"
    if not config_path.exists():
        logger.warning("Config file not found at %s; using env-var defaults", config_path)
        return _fallback_config_from_env()

    cfg = OmegaConf.load(config_path)
    OmegaConf.resolve(cfg)
    return cfg


def _fallback_config_from_env() -> Any:
    """Build a minimal config object from env vars when OmegaConf isn't available.

    Returns a namespace-like object that supports attribute access for the
    keys runtime.py needs.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        etsy=SimpleNamespace(
            keystring=os.environ.get("ETSY_KEYSTRING", ""),
            shared_secret=os.environ.get("ETSY_SHARED_SECRET", ""),
            api_base=os.environ.get("ETSY_API_BASE", "https://api.etsy.com/v3/application"),
            timeout_seconds=float(os.environ.get("ETSY_TIMEOUT_SECONDS", "15")),
            rate_limit_per_second=float(os.environ.get("ETSY_RATE_LIMIT_PER_SECOND", "10")),
            rate_limit_per_day=int(os.environ.get("ETSY_RATE_LIMIT_PER_DAY", "10000")),
            token_store=os.environ.get("ETSY_TOKEN_STORE", ""),
        ),
        server=SimpleNamespace(
            name="etsy-mcp",
            log_level=_LOG_LEVEL,
            permission_mode=os.environ.get("ETSY_TOOL_PERMISSION_MODE", "confirm"),
            diagnostics_enabled=os.environ.get("ETSY_DIAGNOSTICS_ENABLED", "false").lower() == "true",
        ),
    )
