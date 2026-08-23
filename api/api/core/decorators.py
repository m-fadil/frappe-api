from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

import frappe

from .exceptions import BadRequestException
from .logging import log
from .pipes import run_default_pipes, run_pipes
from .request import get_request_data

EndpointFn = Callable[..., Any]


def endpoint(
	*,
	guest: bool = False,
	dto: type | None = None,
	pipes: tuple[Callable[[dict[str, Any]], dict[str, Any]], ...] = (),
	methods: tuple[str, ...] = ("GET",),
) -> Callable[[EndpointFn], EndpointFn]:
	def outer(fn: EndpointFn) -> EndpointFn:
		signature = inspect.signature(fn)
		takes_kwargs = any(p.kind is p.VAR_KEYWORD for p in signature.parameters.values())
		dto_fields = inspect.signature(dto).parameters if dto is not None else {}

		@functools.wraps(fn)
		def invoke(*args: Any, **kwargs: Any) -> Any:
			# payload selalu dibangun dari request, jadi positional arg pasti hilang.
			# Lebih baik gagal keras daripada argumen pemanggil dibuang diam-diam.
			if args:
				raise BadRequestException(
					"Endpoint only accepts keyword arguments",
					code="INVALID_REQUEST_PAYLOAD",
				)

			raw = get_request_data(kwargs)
			raw = run_default_pipes(raw)
			raw = run_pipes(raw, pipes)

			if dto is not None:
				# form_dict membawa query param apa pun (utm_*, token proxy, dsb).
				# Buang yang bukan field DTO: param nyasar bukan alasan untuk 400.
				raw = {key: value for key, value in raw.items() if key in dto_fields}
				try:
					body = dto(**raw)
				except TypeError as exc:
					raise BadRequestException(
						"Invalid request payload",
						code="INVALID_REQUEST_PAYLOAD",
					) from exc
				return fn(body)

			# form_dict membawa semua query param, jadi buang yang tidak diterima fn
			# dan cek kecocokan argumen sebelum memanggil: mismatch = 400, bukan 500.
			if not takes_kwargs:
				raw = {key: value for key, value in raw.items() if key in signature.parameters}
			try:
				signature.bind(**raw)
			except TypeError as exc:
				raise BadRequestException(
					"Invalid request payload",
					code="INVALID_REQUEST_PAYLOAD",
				) from exc

			return fn(**raw)

		return frappe.whitelist(allow_guest=guest, methods=list(methods))(log()(invoke))

	return outer
