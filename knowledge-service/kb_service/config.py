from __future__ import annotations

import os
from pathlib import Path
import yaml


_PATH_KEYS = (
    "project_root", "source_root", "qdrant_path", "lexical_db",
    "manifest_db", "model_cache", "log_dir",
)

# Environment overrides keep deployments free of hard-coded local paths.
_ENV_OVERRIDES = {
    "api_key": "KB_API_KEY",
    "collection": "KB_COLLECTION",
    "qdrant_url": "KB_QDRANT_URL",
    "host": "KB_HOST",
    "port": "KB_PORT",
    "qdrant_path": "KB_QDRANT_PATH",
    "lexical_db": "KB_LEXICAL_DB",
    "manifest_db": "KB_MANIFEST_DB",
    "model_cache": "KB_MODEL_CACHE",
    "log_dir": "KB_LOG_DIR",
    "source_root": "KB_SOURCE_ROOT",
    "project_root": "KB_PROJECT_ROOT",
}


def load_config() -> dict:
    path = Path(os.environ.get("HOTLINE_KB_CONFIG", "config.yaml"))
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key, env_name in _ENV_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value is not None and value != "":
            cfg[key] = value
    for key in _PATH_KEYS:
        cfg[key] = str(Path(cfg[key]))
    if cfg.get("port") is not None:
        cfg["port"] = int(cfg["port"])
    return cfg
