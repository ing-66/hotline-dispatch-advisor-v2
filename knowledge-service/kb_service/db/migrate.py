"""MySQL 迁移工具（CLI）。

命令::

    python -m kb_service.db.migrate --db dev   up
    python -m kb_service.db.migrate --db dev   status
    python -m kb_service.db.migrate --db dev   verify
    python -m kb_service.db.migrate --db dev   health

- 迁移文件目录：db/migrations/（可用 config mysql.migrations_dir 覆盖）
- 记录表：schema_migrations(version, name, checksum, applied_at)
- 文件内容按 ';' 切分逐条执行；执行成功后才写入记录；
  任何语句失败即中止并抛出明确错误（已执行部分依赖幂等写法可安全重跑）。
- 已应用文件被修改（checksum 变化）时拒绝执行。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

from . import health as health_mod
from .config import mysql_config, resolve_migrations_dir

DDL_CONN_PARAMS = dict(charset="utf8mb4", autocommit=True, cursorclass=DictCursor)

# 迁移文件命名：4 位版本号 + 下划线 + 描述 + .sql
MIGRATION_FILE_RE = re.compile(r"^\d{4}_.+\.sql$")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _connect(cfg: dict) -> pymysql.Connection:
    params = dict(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        connect_timeout=cfg["connect_timeout"],
        **DDL_CONN_PARAMS,
    )
    try:
        conn = pymysql.connect(**params)
    except pymysql.MySQLError as exc:
        raise RuntimeError(f"MySQL 连接失败（{cfg['host']}:{cfg['port']}/{cfg['database']}）: {exc}") from exc
    with conn.cursor() as cur:
        cur.execute("SET time_zone = '+00:00'")
    return conn


class Migrator:
    def __init__(self, raw_config: dict, database: str = "dev"):
        cfg = mysql_config(raw_config, database=database)
        # 迁移需要 DDL 权限：优先专用迁移账号，未配置时回退应用账号
        user = cfg.get("migrator_user") or cfg.get("user")
        password = cfg.get("migrator_password") or cfg.get("password")
        if not user or not password:
            raise RuntimeError("MySQL 凭据未配置：请填写 config.yaml 的 mysql: 段或设置 HOTLINE_MYSQL_* 环境变量")
        cfg["user"] = user
        cfg["password"] = password
        self.cfg = cfg
        root = raw_config.get("project_root")
        self.migrations_dir = resolve_migrations_dir(root, cfg.get("migrations_dir"))
        self.conn = _connect(cfg)

    # -- helpers -----------------------------------------------------------
    def _ensure_migrations_table(self) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version    VARCHAR(32)  NOT NULL,
                  name       VARCHAR(200) NOT NULL,
                  checksum   CHAR(64)     NOT NULL,
                  applied_by VARCHAR(64)  NULL,
                  applied_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
                  PRIMARY KEY (version)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
                """
            )

    def _applied(self) -> dict[str, dict]:
        """已应用版本 -> {name, checksum}。"""
        out: dict[str, dict] = {}
        with self.conn.cursor() as cur:
            cur.execute("SELECT version, name, checksum FROM schema_migrations")
            for row in cur.fetchall():
                out[str(row["version"])] = {"name": row["name"], "checksum": row["checksum"]}
        return out

    def _migration_files(self) -> list[tuple[str, str, Path]]:
        """(版本号, 文件名, 路径)，按字典序。

        严格校验：文件名必须为 NNNN_描述.sql（NNNN 为 4 位数字），
        且同一版本号不得出现两个文件（防止改名/复制绕过迁移记录）。
        """
        files = sorted(self.migrations_dir.glob("*.sql"))
        result: list[tuple[str, str, Path]] = []
        for f in files:
            if not MIGRATION_FILE_RE.match(f.name):
                raise RuntimeError(
                    f"迁移文件名不符合规范 NNNN_描述.sql: {f.name}（目录内只允许版本化迁移文件）"
                )
            version = f.name[:4]
            if any(v == version for v, _, _ in result):
                raise RuntimeError(f"版本 {version} 存在多个迁移文件，请保留唯一一个: {self.migrations_dir}")
            result.append((version, f.name, f))
        return result

    @staticmethod
    def _split_statements(sql: str) -> list[str]:
        """按行剔除整行注释后以 ';' 切分。
        迁移文件规范（db/README.md）：注释必须独占整行且以 -- 开头；
        禁止存储过程、触发器与字符串字面量内分号。
        """
        kept = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
        stmts = []
        for part in "\n".join(kept).split(";"):
            part = part.strip()
            if part:
                stmts.append(part)
        return stmts

    # -- commands ----------------------------------------------------------
    def status(self) -> str:
        self._ensure_migrations_table()
        applied = self._applied()
        files = self._migration_files()
        lines = [f"[migrate] 迁移目录: {self.migrations_dir}", f"[migrate] 目标库: {self.cfg['database']}"]
        for version, name, path in files:
            text = path.read_text(encoding="utf-8")
            checksum = _sha256_text(text)
            if version in applied:
                if applied[version]["checksum"] != checksum:
                    lines.append(f"  {version} {name:<48} 已应用但校验失败(文件被改动!)")
                else:
                    lines.append(f"  {version} {name:<48} 已应用")
            else:
                lines.append(f"  {version} {name:<48} 待应用")
        missing = sorted(set(applied) - {v for v, _, _ in files})
        for version in missing:
            lines.append(f"  {version} (记录存在但文件缺失)  -> {applied[version]['name']}")
        return "\n".join(lines)

    def _guard_checksums(self, applied: dict[str, dict], files: list[tuple[str, str, Path]]) -> None:
        """强制校验：已应用迁移的文件若被改动、改名或缺失，一律拒绝继续。

        校验点：
        1) checksum 一致（内容未被改动）；
        2) 文件名一致（防止把已应用版本改名/复制成另一个 NNNN_*.sql 绕过记录）；
        3) 记录的版本在磁盘上存在（防止文件被删除）。
        """
        problems: list[str] = []
        disk = {version: (name, path) for version, name, path in files}
        for version in sorted(applied):
            record_name = applied[version]["name"]
            if version not in disk:
                problems.append(f"{version} ({record_name}): 已应用但迁移文件缺失")
                continue
            name, path = disk[version]
            if name != record_name:
                problems.append(
                    f"{version}: 已应用文件名 {record_name} 与磁盘文件 {name} 不一致"
                    "（迁移文件不得改名或复制）"
                )
                continue
            current = _sha256_text(path.read_text(encoding="utf-8"))
            if applied[version]["checksum"] != current:
                problems.append(
                    f"{version} {name}: 已应用但文件被改动（记录={applied[version]['checksum']}, 当前={current}）"
                )
        if problems:
            raise RuntimeError(
                "迁移完整性校验失败，已拒绝执行：\n  " + "\n  ".join(problems) +
                "\n修复方式：如需变更结构请新增 NNNN_*.sql 迁移，不得修改、改名或删除已应用文件。"
            )

    def up(self) -> str:
        self._ensure_migrations_table()
        applied = self._applied()
        files = self._migration_files()
        self._guard_checksums(applied, files)  # 强制：已应用文件被改动则拒绝
        ran: list[str] = []
        for version, name, path in files:
            if version in applied:
                continue
            text = path.read_text(encoding="utf-8")
            checksum = _sha256_text(text)
            statements = self._split_statements(text)
            if not statements:
                raise RuntimeError(f"迁移文件 {name} 无有效语句")
            with self.conn.cursor() as cur:
                for i, stmt in enumerate(statements, start=1):
                    try:
                        cur.execute(stmt)
                    except pymysql.MySQLError as exc:
                        snippet = stmt.replace("\n", " ")[:80]
                        raise RuntimeError(
                            f"迁移 {name} 第 {i} 条语句失败: {exc}\n语句: {snippet}\n"
                            f"提示：语句已按幂等写法设计，修复后可重新执行本命令继续。"
                        ) from exc
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO schema_migrations (version, name, checksum, applied_by) VALUES (%s, %s, %s, %s)",
                    (version, name, checksum, "kb_service.db.migrate"),
                )
            ran.append(f"{version} {name}")
        if not ran:
            return f"[migrate] 无需执行：{self.cfg['database']} 已是最新结构（共 {len(files)} 个迁移文件）"
        return f"[migrate] 已应用 {len(ran)} 个迁移:\n  " + "\n  ".join(ran)

    def verify(self) -> str:
        """连接健康 + 迁移记录与库内业务表核对 + 已应用迁移 checksum 强制校验。"""
        self._ensure_migrations_table()
        applied = self._applied()
        files = self._migration_files()
        self._guard_checksums(applied, files)  # 强制：文件被改动/缺失则 verify 失败
        with self.conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS v, @@session.time_zone AS tz, @@character_set_server AS cs")
            row = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name <> 'schema_migrations'",
                (self.cfg["database"],),
            )
            table_count = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM schema_migrations")
            applied_count = cur.fetchone()["c"]
        return (
            f"[migrate] verify OK  db={self.cfg['database']}  version={row['v']}  "
            f"time_zone={row['tz']}  charset={row['cs']}\n"
            f"[migrate] 业务表={table_count}  已应用迁移={applied_count}  checksum 全部一致"
        )

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_service.db.migrate", description="MySQL 迁移工具")
    parser.add_argument("command", choices=["up", "status", "verify", "health"], help="执行命令")
    parser.add_argument("--db", choices=["dev", "test"], default="dev", help="目标库类型（默认 dev）")
    parser.add_argument("--config", default="config.yaml", help="主配置路径（默认 config.yaml）")
    args = parser.parse_args(argv)

    import yaml

    try:
        with open(args.config, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        raw.setdefault("project_root", str(Path(args.config).resolve().parent))
    except OSError as exc:
        print(f"[migrate] 无法读取配置 {args.config}: {exc}", file=sys.stderr)
        return 2

    if args.command == "health":
        result = health_mod.check_mysql(raw, database=args.db)
        print(health_mod.format_check(result))
        return 0 if result.get("ok") or not result.get("enabled") else 1

    try:
        migrator = Migrator(raw, database=args.db)
    except RuntimeError as exc:
        print(f"[migrate] 错误: {exc}", file=sys.stderr)
        return 1
    try:
        if args.command == "status":
            print(migrator.status())
        elif args.command == "up":
            print(migrator.up())
        elif args.command == "verify":
            print(migrator.verify())
    except RuntimeError as exc:
        print(f"[migrate] 错误: {exc}", file=sys.stderr)
        return 1
    finally:
        migrator.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
