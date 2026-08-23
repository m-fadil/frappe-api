from __future__ import annotations

import functools
import json
import time
from collections.abc import Callable
from typing import Any

import frappe
from frappe.utils import cstr

from .exceptions import (
	ApiException,
	ForbiddenException,
	ServiceUnavailableException,
)

DEFAULT_SENSITIVE_FIELDS = {
	"password",
	"token",
	"auth",
	"secret",
	"api_key",
	"api_secret",
	"access_token",
	"refresh_token",
	"credit_card",
	"cvv",
	"authorization",
	"cookie",
}


def _get_error_title(status_code: int) -> str:
	return {
		400: "Bad Request",
		401: "Unauthorized",
		403: "Forbidden",
		404: "Not Found",
		405: "Method Not Allowed",
		406: "Not Acceptable",
		408: "Request Timeout",
		409: "Conflict",
		410: "Gone",
		412: "Precondition Failed",
		413: "Payload Too Large",
		415: "Unsupported Media Type",
		418: "I'm a teapot",
		422: "Unprocessable Entity",
		500: "Internal Server Error",
		501: "Not Implemented",
		502: "Bad Gateway",
		503: "Service Unavailable",
		504: "Gateway Timeout",
		505: "HTTP Version Not Supported",
	}.get(status_code, "Error")


def _to_legacy_error_response(exc: ApiException) -> dict[str, Any]:
	response: dict[str, Any] = {
		"_status_code": exc.status_code,
		"_title": _get_error_title(exc.status_code),
		"_detail": exc.message,
	}
	if exc.code:
		response["_code"] = exc.code
	if exc.payload:
		response["_payload"] = exc.payload
	return response


def _get_settings() -> dict[str, Any]:
	try:
		from api.rest_api.doctype.api_settings.api_settings import get_settings

		return get_settings()
	except Exception:
		return {
			"enable_api": 1,
			"allow_guest_access": 1,
			"enable_logging": 1,
			"log_errors_only": 0,
			"log_request_payload": 1,
			"log_response_payload": 1,
			"log_headers": 1,
			"mask_sensitive_data": 1,
			"sensitive_fields": "password, token, auth, secret, api_key, api_secret, access_token, refresh_token, credit_card, cvv",
			"auto_cleanup": 1,
			"retention_days": 30,
			"max_payload_size_kb": 64,
			"excluded_endpoints": "",
		}


def _get_current_user() -> str:
	try:
		if hasattr(frappe, "session"):
			return getattr(frappe.session, "user", "Guest") or "Guest"
	except Exception:
		pass
	return "Guest"


def _get_sensitive_keys(settings: dict[str, Any]) -> set[str]:
	raw = settings.get("sensitive_fields") or ""
	keys = {k.strip().lower() for k in raw.split(",") if k.strip()}
	return keys or DEFAULT_SENSITIVE_FIELDS


def _mask_data(data: Any, sensitive_keys: set[str]) -> Any:
	if isinstance(data, dict):
		masked = {}
		for k, v in data.items():
			if isinstance(k, str) and any(sk in k.lower() for sk in sensitive_keys):
				masked[k] = "********"
			else:
				masked[k] = _mask_data(v, sensitive_keys)
		return masked
	elif isinstance(data, list | tuple):
		return [_mask_data(item, sensitive_keys) for item in data]
	return data


def _safe_serialize(data: Any, sensitive_keys: set[str] | None = None, max_kb: int = 64) -> str | None:
	if data is None:
		return None
	try:
		if sensitive_keys:
			data = _mask_data(data, sensitive_keys)
		serialized = json.dumps(data, indent=2, default=cstr, ensure_ascii=False)
		max_bytes = max_kb * 1024
		if len(serialized.encode("utf-8")) > max_bytes:
			serialized = serialized[:max_bytes] + "\n... [TRUNCATED DUE TO SIZE LIMIT]"
		return serialized
	except Exception as err:
		return f"<Serialization Error: {err}>"


def _extract_request_context() -> dict[str, Any]:
	ctx: dict[str, Any] = {
		"user": _get_current_user(),
		"ip_address": None,
		"method": "GET",
		"path": None,
		"headers": None,
		"user_agent": None,
		"host": None,
	}

	try:
		if hasattr(frappe, "local"):
			ctx["ip_address"] = getattr(frappe.local, "request_ip", None)
	except Exception:
		pass

	try:
		req = getattr(frappe, "request", None)
		if req:
			ctx["method"] = getattr(req, "method", "GET") or "GET"
			ctx["path"] = getattr(req, "path", None)
			ctx["user_agent"] = req.headers.get("User-Agent") if hasattr(req, "headers") else None
			ctx["host"] = req.headers.get("Host") if hasattr(req, "headers") else None
			if not ctx["ip_address"]:
				ctx["ip_address"] = getattr(req, "remote_addr", None)
			if hasattr(req, "headers"):
				ctx["headers"] = dict(req.headers)
	except Exception:
		pass

	return ctx


def record_api_log(
	*,
	endpoint: str,
	status_code: int,
	execution_time_ms: float,
	request_data: Any = None,
	response_data: Any = None,
	error_code: str | None = None,
	error_message: str | None = None,
	traceback_str: str | None = None,
) -> None:
	try:
		settings = _get_settings()
		if not settings.get("enable_logging", 1):
			return

		if settings.get("log_errors_only", 0) and status_code < 400:
			return

		excluded = settings.get("excluded_endpoints") or ""
		if excluded:
			excluded_list = [e.strip() for e in excluded.replace("\n", ",").split(",") if e.strip()]
			if endpoint in excluded_list:
				return

		sensitive_keys = (
			_get_sensitive_keys(settings) if settings.get("mask_sensitive_data", 1) else set()
		)
		max_kb = int(settings.get("max_payload_size_kb") or 64)

		ctx = _extract_request_context()
		path = ctx["path"] or endpoint
		method = ctx["method"]

		headers_str = None
		if settings.get("log_headers", 1) and ctx["headers"]:
			headers_str = _safe_serialize(ctx["headers"], sensitive_keys=sensitive_keys, max_kb=max_kb)

		req_str = None
		if settings.get("log_request_payload", 1) and request_data is not None:
			req_str = _safe_serialize(request_data, sensitive_keys=sensitive_keys, max_kb=max_kb)

		res_str = None
		if settings.get("log_response_payload", 1) and response_data is not None:
			res_str = _safe_serialize(response_data, sensitive_keys=sensitive_keys, max_kb=max_kb)

		try:
			has_db = hasattr(frappe, "db") and frappe.db is not None
		except Exception:
			has_db = False

		if not has_db:
			return

		status = "Success" if status_code < 400 else "Error"
		title = f"[{method}] {status_code} {endpoint or path}".strip()

		doc = frappe.get_doc({
			"doctype": "API Log",
			"title": title,
			"status": status,
			"status_code": status_code,
			"method": method,
			"path": path,
			"endpoint": endpoint,
			"execution_time": round(execution_time_ms, 2),
			"user": ctx["user"],
			"ip_address": ctx["ip_address"],
			"headers": headers_str,
			"request_data": req_str,
			"response_data": res_str,
			"error_code": error_code,
			"error_message": error_message,
			"traceback": traceback_str,
			"user_agent": ctx["user_agent"],
			"host": ctx["host"],
		})
		doc.flags.ignore_permissions = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)

		try:
			if hasattr(frappe.db, "commit"):
				frappe.db.commit()
		except Exception:
			pass
	except Exception:
		pass


def log():
	def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
		endpoint_name = f"{fn.__module__}.{fn.__qualname__}"

		@functools.wraps(fn)
		def invoke(*args: Any, **kwargs: Any) -> Any:
			settings = _get_settings()

			if not settings.get("enable_api", 1):
				raise ServiceUnavailableException(
					"API service is currently disabled",
					code="API_DISABLED",
				)

			user = _get_current_user()
			if user == "Guest" and not settings.get("allow_guest_access", 1):
				raise ForbiddenException(
					"Guest access to API is disabled",
					code="GUEST_ACCESS_DISABLED",
				)

			start_time = time.perf_counter()
			req_payload = kwargs if kwargs else (args[0] if args else None)

			try:
				result = fn(*args, **kwargs)
				elapsed_ms = (time.perf_counter() - start_time) * 1000
				record_api_log(
					endpoint=endpoint_name,
					status_code=200,
					execution_time_ms=elapsed_ms,
					request_data=req_payload,
					response_data=result,
				)
				return result

			except ApiException as exc:
				elapsed_ms = (time.perf_counter() - start_time) * 1000
				err_resp = _to_legacy_error_response(exc)

				try:
					if hasattr(frappe, "local") and hasattr(frappe.local, "response"):
						frappe.local.response["http_status_code"] = exc.status_code
				except Exception:
					pass

				record_api_log(
					endpoint=endpoint_name,
					status_code=exc.status_code,
					execution_time_ms=elapsed_ms,
					request_data=req_payload,
					response_data=err_resp,
					error_code=exc.code,
					error_message=exc.message,
				)
				return err_resp

			except Exception as exc:
				elapsed_ms = (time.perf_counter() - start_time) * 1000
				tb = None
				try:
					tb = frappe.get_traceback()
				except Exception:
					pass

				err_resp = {
					"_status_code": 500,
					"_title": "Internal Server Error",
					"_detail": str(exc) or "An unexpected error occurred",
					"_code": "INTERNAL_SERVER_ERROR",
				}

				try:
					if hasattr(frappe, "local") and hasattr(frappe.local, "response"):
						frappe.local.response["http_status_code"] = 500
				except Exception:
					pass

				record_api_log(
					endpoint=endpoint_name,
					status_code=500,
					execution_time_ms=elapsed_ms,
					request_data=req_payload,
					response_data=err_resp,
					error_code="INTERNAL_SERVER_ERROR",
					error_message=str(exc),
					traceback_str=tb,
				)
				return err_resp

		return invoke

	return decorate
