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


def get_session():
    with Session(engine) as session:
        yield session


def init_db():
    # 导入模型确保注册
    from app.models import user, goal, task, execution, log, memory  # noqa: F401

    SQLModel.metadata.create_all(engine)
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

                existing = session.get(User, 1)
                if not existing:
                    u = User(id=1, username="demo", password_hash="demo", major="计算机", learning_style="visual")
                    session.add(u)
                    session.commit()
            except Exception as e:
                # 忽略种子失败，不阻断启动
                print(f"[init_db] seed skip: {e}")
