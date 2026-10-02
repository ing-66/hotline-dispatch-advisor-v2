"""MySQL 连接配置读取。

优先级：config.yaml 的 ``mysql:`` 段 <- 环境变量 ``HOTLINE_MYSQL_*`` 覆盖。
凭据只在本模块内组装并传给驱动，禁止打印、记录或写入日志/报告。
"""
from __future__ import annotations

import os
from pathlib import Path

# 环境变量覆盖（用于 CI / 部署，避免密钥落盘）
_ENV_MAP = {
    "enabled": "HOTLINE_MYSQL_ENABLED",
    "host": "HOTLINE_MYSQL_HOST",
    "port": "HOTLINE_MYSQL_PORT",
    "user": "HOTLINE_MYSQL_USER",
    "password": "HOTLINE_MYSQL_PASSWORD",
    "migrator_user": "HOTLINE_MYSQL_MIGRATOR_USER",
    "migrator_password": "HOTLINE_MYSQL_MIGRATOR_PASSWORD",
    "dev_db": "HOTLINE_MYSQL_DEV_DB",
    "test_db": "HOTLINE_MYSQL_TEST_DB",
}

DEFAULT_MYSQL = {
    "enabled": False,
    "host": "127.0.0.1",
    "port": 3306,
    "user": "",
    "password": "",
    "migrator_user": "",
    "migrator_password": "",
    "dev_db": "hotline_dispatch_dev",
    "test_db": "hotline_dispatch_test",
    "migrations_dir": "db/migrations",
    "connect_timeout": 5,
    "pool_size": 5,
}


def _as_bool(v: str | bool) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def mysql_config(raw_config: dict | None = None, database: str = "dev") -> dict:
    """从主配置或独立 dict 读取 mysql 段并应用环境变量覆盖。

    返回完整 mysql 段 dict（键与 DEFAULT_MYSQL 对齐）。database 仅用于选择
    database 字段：dev -> dev_db / test -> test_db。
    """
    raw = (raw_config or {}).get("mysql") or {}
    cfg = dict(DEFAULT_MYSQL)
    cfg.update({k: v for k, v in raw.items() if k in cfg})
    # 环境变量覆盖
    for key, env in _ENV_MAP.items():
        val = os.environ.get(env)
        if val is not None and val != "":
            cfg[key] = _as_bool(val) if key == "enabled" else val
    if cfg["port"] is not None:
        cfg["port"] = int(cfg["port"])
    cfg["pool_size"] = int(cfg["pool_size"])
    cfg["connect_timeout"] = int(cfg["connect_timeout"])
    db_name = cfg.get("test_db") if database == "test" else cfg.get("dev_db")
    cfg["database"] = db_name
    return cfg


def resolve_migrations_dir(project_root: str | Path | None, configured: str | None) -> Path:
    """迁移目录：优先 mysql.migrations_dir（相对项目根解析），缺省 db/migrations。"""
    root = Path(project_root) if project_root else Path.cwd()
    if configured:
        p = Path(configured)
        return p if p.is_absolute() else root / p
    return root / "db" / "migrations"


def is_enabled(raw_config: dict | None = None) -> bool:
    return _as_bool((raw_config or {}).get("mysql", {}).get("enabled", False)) or _as_bool(
        os.environ.get(_ENV_MAP["enabled"], "0")
    )
