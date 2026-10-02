"""MySQL 数据访问层（阶段1 基础框架）。

边界约定（见 migration/phase1/PHASE1_DESIGN.md §7）：
- 所有 MySQL 访问只允许经本包进行，业务代码禁止散落裸 SQL。
- 本包与现有 SQLite 访问（kb_service/store.py、web/lib/store.js）并存但不互引，
  后续阶段以 repository 接口收口后替换。
"""
__all__ = []

from .pool import MysqlPool, get_pool, configure_pool, close_all  # noqa: E402
from .health import check_mysql  # noqa: E402

__all__ = ["MysqlPool", "get_pool", "configure_pool", "close_all", "check_mysql"]
