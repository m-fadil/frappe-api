from __future__ import annotations

from collections.abc import Callable
from typing import Any

Pipe = Callable[[dict[str, Any]], dict[str, Any]]


def trim_value(value: Any) -> Any:
	if isinstance(value, str):
		return value.strip()
	return value


def run_default_pipes(data: dict[str, Any]) -> dict[str, Any]:
	return {key: trim_value(value) for key, value in data.items() if key != "cmd"}


def run_pipes(data: dict[str, Any], pipes: tuple[Pipe, ...] = ()) -> dict[str, Any]:
	for pipe in pipes:
		data = pipe(data)
	return data
