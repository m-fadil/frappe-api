from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

import frappe

from .exceptions import BadRequestException
from .logging import STANDARD, Telemetry, log
from .pipes import run_default_pipes, run_pipes
from .policies import DEFAULT_POLICIES, Policy, RequestContext
from .request import get_request_data

EndpointFn = Callable[..., Any]


def endpoint(
	*,
	guest: bool = False,
	xss_safe: bool = False,
	dto: type | None = None,
	pipes: tuple[Callable[[dict[str, Any]], dict[str, Any]], ...] = (),
	methods: tuple[str, ...] = ("GET",),
	policies: tuple[Policy, ...] | None = None,
	normalize: bool = True,
	telemetry: Telemetry = STANDARD,
) -> Callable[[EndpointFn], EndpointFn]:
	"""Compose access checks, payload validation and observation independently.

	None selects default policies; an explicit tuple replaces them, including ().
	Credential endpoints disable normalization and use auth metadata-only telemetry.
	"""
	selected_policies = DEFAULT_POLICIES if policies is None else policies

	def outer(fn: EndpointFn) -> EndpointFn:
		signature = inspect.signature(fn)
		endpoint_name = f"{fn.__module__}.{fn.__qualname__}"
		takes_kwargs = any(p.kind is p.VAR_KEYWORD for p in signature.parameters.values())
		dto_fields = inspect.signature(dto).parameters if dto is not None else {}

		@functools.wraps(fn)
		def invoke(*args: Any, **kwargs: Any) -> Any:
			request = getattr(frappe.local, "request", None)
			session = getattr(frappe, "session", None)
			context = RequestContext(
				user=getattr(session, "user", None) or "Guest",
				method=getattr(request, "method", "GET"),
				endpoint=endpoint_name,
			)
			for policy in selected_policies:
				policy(context)

			# payload selalu dibangun dari request, jadi positional arg pasti hilang.
			# Lebih baik gagal keras daripada argumen pemanggil dibuang diam-diam.
			if args:
				raise BadRequestException(
					"Endpoint only accepts keyword arguments",
					code="INVALID_REQUEST_PAYLOAD",
				)

			raw = get_request_data(kwargs)
			if normalize:
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

		observed = log(telemetry=telemetry)(invoke)
		return frappe.whitelist(allow_guest=guest, xss_safe=xss_safe, methods=list(methods))(observed)

	return outer
