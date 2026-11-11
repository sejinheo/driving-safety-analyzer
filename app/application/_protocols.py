from collections.abc import Callable
from typing import Any, Protocol


class BackgroundTasks(Protocol):
    def add_task(self, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> None: ...


class DbConfig(Protocol):
    database_url: str
    db_pool_min_size: int
    db_pool_max_size: int
