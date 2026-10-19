import json
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent / "config.json"
LOCAL_CONFIG_FILE = Path(__file__).resolve().parent / "config.local.json"

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "text_model": "qwen-plus",
    "enable_tools": True,
    "neo4j_uri": "",
    "neo4j_user": "",
    "neo4j_password": "",
    "neo4j_database": "",
    "max_parallel_experts": 7,
    "max_parallel_queries": 3
}

def load_config():
    config = {}
    for path in (CONFIG_FILE, LOCAL_CONFIG_FILE):
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    config.update(loaded)
        except (OSError, ValueError):
            continue
    merged = {**DEFAULT_CONFIG, **config}
    # Explicit project variables override the saved configuration. Do not copy
    # credentials belonging to the coding agent into the application's config.
    for key in ("api_key", "base_url", "text_model", "neo4j_uri",
                "neo4j_user", "neo4j_password", "neo4j_database"):
        value = os.environ.get("GDGPT_" + key.upper())
        if value:
            merged[key] = value
    return merged

def save_config(config_dict):
    try:
        fd = os.open(LOCAL_CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(LOCAL_CONFIG_FILE, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=4)
        return True
    except Exception as e:
        print(f"Save config failed: {e}")
        return False
