import os
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

settings = get_settings()

# P0: 默认用 SQLite 文件，保证无 Docker 也可跑；PG 需显式开启 USE_PG=1
USE_PG = os.getenv("USE_PG", "0") == "1"
DATABASE_URL = settings.database_url

if USE_PG and DATABASE_URL.startswith("postgresql"):
    db_url = DATABASE_URL
    connect_args = {}
else:
    # fallback sqlite
    data_dir = Path(__file__).parent.parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "app.db"
    db_url = f"sqlite:///{db_path}"
    connect_args = {"check_same_thread": False}

engine = create_engine(db_url, echo=False, connect_args=connect_args)

# H-03: SQLite 启用 WAL + busy_timeout 降低并发锁（对标 Pi SessionState 的附加日志串行化）
if not USE_PG:
    try:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL;"))
            conn.execute(text("PRAGMA synchronous=NORMAL;"))
            conn.execute(text("PRAGMA busy_timeout=5000;"))
            conn.commit()
    except Exception as e:
        print(f"[db] WAL setup failed: {e}")
else:
    # H-04 pgvector：USE_PG=1 时尝试启用 vector 扩展（H-04/P1）
    try:
        from app.models.memory import _USE_PG_VECTOR

        if _USE_PG_VECTOR:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.commit()
                # 尝试建 HNSW 索引（若表已存在则跳过，首次建表后由 init_db 兜底）
                try:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_memory_embedding_hnsw ON memory_chunk USING hnsw (embedding vector_cosine_ops);"))
                    conn.commit()
                except Exception as ie:
                    # 索引可能因表不存在而失败，留给 init_db 后重试
                    print(f"[db] hnsw index deferred: {ie}")
    except Exception as e:
        print(f"[db] vector extension skip: {e}")

# 细致收口：全链 Async 引擎（aiosqlite/asyncpg）与 WAL 互补，P0-1 要求
try:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

    if USE_PG and DATABASE_URL.startswith("postgresql"):
        db_url_async = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://").replace("postgresql+psycopg://", "postgresql+asyncpg://")
        async_connect_args = {}
    else:
        # 异步 SQLite 需 aiosqlite 驱动，路径同 sync
        data_dir_async = Path(__file__).parent.parent.parent / "data"
        data_dir_async.mkdir(parents=True, exist_ok=True)
        db_path_async = data_dir_async / "app.db"
        db_url_async = f"sqlite+aiosqlite:///{db_path_async}"
        async_connect_args = {}
    async_engine = create_async_engine(db_url_async, echo=False, connect_args=async_connect_args)
    async_session_factory = async_sessionmaker(async_engine, class_=SAAsyncSession, expire_on_commit=False)
except Exception as e:
    print(f"[db] async engine skip: {e}")
    async_engine = None  # type: ignore
    async_session_factory = None  # type: ignore


def get_session():
    with Session(engine) as session:
        yield session


async def get_async_session():  # type: ignore
    """真正的 AsyncSession（aiosqlite/asyncpg），供新路由直接 await 使用"""
    if async_session_factory is None:
        # 回退：用线程池包同步 Session（保持兼容）
        with Session(engine) as session:
            yield session
        return
    async with async_session_factory() as session:  # type: ignore
        yield session


async def aget_session():  # type: ignore
    """兼容别名，同 get_async_session"""
    async for s in get_async_session():
        yield s


async def run_db(func, *args, **kwargs):
    """将同步 DB 操作放到线程池（H-03 兜底，供旧同步代码在 async 中调用）"""
    import asyncio

    return await asyncio.to_thread(func, *args, **kwargs)


def init_db():
    # 导入模型确保注册
    from app.models import execution, goal, log, memory, reflection, task, user  # noqa: F401

    # 若 PG + vector，预先确保扩展存在再建表（避免 Vector 类型建表失败）
    if USE_PG:
        try:
            from app.models.memory import _USE_PG_VECTOR

            if _USE_PG_VECTOR:
                with engine.connect() as conn:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                    conn.commit()
        except Exception:
            pass
    SQLModel.metadata.create_all(engine)
    # 性能索引：task_execution_log / task / learning_goal（对齐 stats trend 单查询）
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_exec_created ON task_execution_log(created_at);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_exec_task ON task_execution_log(task_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_task_goal ON task(goal_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_task_start ON task(planned_start);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_goal_user ON learning_goal(user_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_memory_user_type ON memory_chunk(user_id, type);"))
            # 工作台：agent_run_log 联合索引 (trace_id, agent_name, created_at) 供 Graph/Inspector 重放，含单列回退
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_trace ON agent_run_log(trace_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_trace_agent_created ON agent_run_log(trace_id, agent_name, created_at);"))
            conn.commit()
    except Exception as e:
        print(f"[db] perf index skip: {e}")
    # PG + vector：建 HNSW 索引（幂等）
    if USE_PG:
        try:
            from app.models.memory import _USE_PG_VECTOR

            if _USE_PG_VECTOR:
                with engine.connect() as conn:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_memory_embedding_hnsw ON memory_chunk USING hnsw (embedding vector_cosine_ops);"))
                    conn.commit()
        except Exception as e:
            print(f"[db] pgvector index skip: {e}")
    # 种子用户 id=1
    with Session(engine) as session:
        try:
            # 建表后检查 user 1
            result = session.exec(text("SELECT 1 FROM \"user\" WHERE id=1"))
            # 若无表或无数据则走 except
            if result.first() is None:
                raise Exception("seed needed")
        except Exception:
            # 尝试 SQLModel 方式
            try:
                from app.models.user import User

                def _hash_demo(pwd: str = "demo123") -> str:
                    try:
                        from passlib.context import CryptContext

                        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
                        return ctx.hash(pwd)
                    except Exception:
                        import hashlib

                        return hashlib.sha256(pwd.encode()).hexdigest()

                existing = session.get(User, 1)
                if not existing:
                    u = User(id=1, username="demo", password_hash=_hash_demo("demo123"), major="计算机", learning_style="visual")
                    session.add(u)
                    session.commit()
                elif existing.password_hash == "demo":
                    # 升级旧明文 demo 为 hash（兼容 05-API 6-64 校验）
                    existing.password_hash = _hash_demo("demo123")
                    session.add(existing)
                    session.commit()
            except Exception as e:
                # 忽略种子失败，不阻断启动
                print(f"[init_db] seed skip: {e}")
    # 兜底：若 seed 已存在但为旧明文 demo，强制升级（外层 SELECT 未触发时）
    try:
        from app.models.user import User

        with Session(engine) as s2:
            u = s2.get(User, 1)
            if u and u.password_hash == "demo":
                try:
                    from passlib.context import CryptContext

                    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
                    u.password_hash = ctx.hash("demo123")
                except Exception:
                    import hashlib

                    u.password_hash = hashlib.sha256("demo123".encode()).hexdigest()
                s2.add(u)
                s2.commit()
    except Exception:
        pass
