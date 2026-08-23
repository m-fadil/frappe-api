from __future__ import annotations

from typing import Any


class ApiException(Exception):
	def __init__(
		self,
		message: str,
		status_code: int,
		code: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message)
		self.message = message
		self.status_code = status_code
		self.http_status_code = status_code
		self.code = code
		self.payload = payload or {}


class BadRequestException(ApiException):
	def __init__(
		self, message: str = "Bad Request", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=400, code=code, payload=payload)


class UnauthorizedException(ApiException):
	def __init__(
		self, message: str = "Unauthorized", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=401, code=code, payload=payload)


class ForbiddenException(ApiException):
	def __init__(
		self, message: str = "Forbidden", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=403, code=code, payload=payload)


class NotFoundException(ApiException):
	def __init__(
		self, message: str = "Not Found", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=404, code=code, payload=payload)


class MethodNotAllowedException(ApiException):
	def __init__(
		self,
		message: str = "Method Not Allowed",
		code: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message=message, status_code=405, code=code, payload=payload)


class NotAcceptableException(ApiException):
	def __init__(
		self, message: str = "Not Acceptable", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=406, code=code, payload=payload)


class RequestTimeoutException(ApiException):
	def __init__(
		self, message: str = "Request Timeout", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=408, code=code, payload=payload)


class ConflictException(ApiException):
	def __init__(
		self, message: str = "Conflict", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=409, code=code, payload=payload)


class GoneException(ApiException):
	def __init__(
		self, message: str = "Gone", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=410, code=code, payload=payload)


class PreconditionFailedException(ApiException):
	def __init__(
		self,
		message: str = "Precondition Failed",
		code: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message=message, status_code=412, code=code, payload=payload)


class PayloadTooLargeException(ApiException):
	def __init__(
		self,
		message: str = "Payload Too Large",
		code: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message=message, status_code=413, code=code, payload=payload)


class UnsupportedMediaTypeException(ApiException):
	def __init__(
		self,
		message: str = "Unsupported Media Type",
		code: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message=message, status_code=415, code=code, payload=payload)


class ImATeapotException(ApiException):
	def __init__(
		self, message: str = "I'm a teapot", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=418, code=code, payload=payload)


class UnprocessableEntityException(ApiException):
	def __init__(
		self,
		message: str = "Unprocessable Entity",
		code: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message=message, status_code=422, code=code, payload=payload)


class InternalServerErrorException(ApiException):
	def __init__(
		self,
		message: str = "Internal Server Error",
		code: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message=message, status_code=500, code=code, payload=payload)


class NotImplementedException(ApiException):
	def __init__(
		self, message: str = "Not Implemented", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=501, code=code, payload=payload)


class BadGatewayException(ApiException):
	def __init__(
		self, message: str = "Bad Gateway", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=502, code=code, payload=payload)


class ServiceUnavailableException(ApiException):
	def __init__(
		self,
		message: str = "Service Unavailable",
		code: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message=message, status_code=503, code=code, payload=payload)


class GatewayTimeoutException(ApiException):
	def __init__(
		self, message: str = "Gateway Timeout", code: str | None = None, payload: dict[str, Any] | None = None
	) -> None:
		super().__init__(message=message, status_code=504, code=code, payload=payload)


class HttpVersionNotSupportedException(ApiException):
	def __init__(
		self,
		message: str = "HTTP Version Not Supported",
		code: str | None = None,
		payload: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message=message, status_code=505, code=code, payload=payload)
