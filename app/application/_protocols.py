from collections.abc import Callable
from typing import Any, Protocol


class BackgroundTasks(Protocol):
    def add_task(self, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> None: ...


class CancelEvent(Protocol):
    def is_set(self) -> bool: ...
