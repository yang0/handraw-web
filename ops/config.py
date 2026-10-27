#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Handraw Web - Environment Configuration Manager
Strictly separates Local Development and Online Production environments.
Reads from config/environments.json, .env.local, .env.production, and OS environment.
"""

import os
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
ENV_JSON_FILE = CONFIG_DIR / "environments.json"


def load_env_file(filepath: Path) -> dict:
    """Parses a key=value .env file without external dependencies."""
    result = {}
    if not filepath.exists():
        return result
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip().strip("'\"")
    except Exception as e:
        print(f"[!] Warning reading {filepath.name}: {e}")
    return result


def get_config(env_name=None, cli_overrides=None) -> dict:
    """
    Resolves the full environment configuration.
    Priority:
    1. CLI overrides
    2. OS Environment variables
    3. .env.local (if local) or .env
    4. config/environments.json
    """
    # 1. Load baseline JSON configurations
    baseline = {}
    if ENV_JSON_FILE.exists():
        try:
            with open(ENV_JSON_FILE, "r", encoding="utf-8") as f:
                baseline = json.load(f)
        except Exception as e:
            print(f"[!] Warning reading {ENV_JSON_FILE.name}: {e}")

    # Determine environment target
    env = env_name or os.environ.get("HANDRAW_ENV") or "local"
    cfg = dict(baseline.get(env, baseline.get("local", {})))

    # 2. Load file-based .env
    env_file = REPO_ROOT / f".env.{env}"
    if not env_file.exists() and env == "local":
        env_file = REPO_ROOT / ".env"
    file_vars = load_env_file(env_file)

    # 3. Merge .env variables into config
    mapping = {
        "HANDRAW_PORT": ("port", int),
        "HANDRAW_HOST": ("host", str),
        "HANDRAW_BASE_URL": ("base_url", str),
        "HANDRAW_DISCOURSE_MODE": ("discourse_mode", str),
        "HANDRAW_DISCOURSE_URL": ("discourse_url", str),
        "HANDRAW_IMAGE_URL": ("image_url", str),
        "HANDRAW_STATIC_URL": ("static_url", str),
        "HANDRAW_GALLERY_URL": ("gallery_url", str),
        "HANDRAW_IMAGE_SERVICE_URL": ("image_service_url", str),
        "HANDRAW_IMAGE_SERVICE_MODE": ("image_service_mode", str),
        "HANDRAW_STORAGE_FILE": ("storage_file", str),
        "HANDRAW_OFFLINE_IMAGES": ("offline_images", lambda x: x.lower() in ["1", "true", "yes"]),
    }

    # Merge from file
    for env_k, (cfg_k, converter) in mapping.items():
        if env_k in file_vars:
            try:
                cfg[cfg_k] = converter(file_vars[env_k])
            except Exception:
                cfg[cfg_k] = file_vars[env_k]

    # Merge from OS environment
    for env_k, (cfg_k, converter) in mapping.items():
        if env_k in os.environ:
            try:
                cfg[cfg_k] = converter(os.environ[env_k])
            except Exception:
                cfg[cfg_k] = os.environ[env_k]

    # 4. CLI overrides (highest priority)
    if cli_overrides:
        for k, v in cli_overrides.items():
            if v is not None:
                cfg[k] = v

    # Helper booleans
    cfg["is_local"] = (cfg.get("env") == "local")
    cfg["is_production"] = (cfg.get("env") == "production")

    return cfg


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "local"
    c = get_config(target)
    print(f"=== Config for '{target}' ===")
    print(json.dumps(c, ensure_ascii=False, indent=2))
