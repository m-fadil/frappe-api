"""Opaque refresh sessions with an absolute family lifetime.

Each operation owns a separate database connection and commits only its own
transaction. In particular, replay revocation is committed *before* raising
AuthenticationError, so Frappe's request rollback cannot undo it or accidentally
commit unrelated request writes. Successful issuance, rotation and logout are
also independent of a surrounding request rollback.

The original token row is the permanent family lock (its name equals family_id).
All consumers lock it before locking an individual token. Used rows must remain
in the database until the family expires so a replay can revoke every descendant.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import frappe
from frappe.database import get_db
from frappe.utils import get_datetime, now_datetime

from api.services.auth.settings import get_jwt_settings

if TYPE_CHECKING:
	from frappe.database.database import Database


_MAX_TOKEN_LENGTH = 512
_INVALID_TOKEN = "Invalid or expired refresh token"


def create_session(user: str, client_id: str | None = None) -> str:
	"""Create and persist a new refresh family; return its only plaintext copy."""
	if client_id is not None and (not isinstance(client_id, str) or len(client_id) > 140):
		raise frappe.ValidationError("client_id must be a string of at most 140 characters")

	ttl = get_jwt_settings()["refresh_ttl"]
	now = now_datetime()
	family_id = secrets.token_hex(16)
	with _transaction() as db:
		_require_enabled_user(db, user)
		token, _name = _insert_token(
			db,
			user=user,
			client_id=client_id,
			family_id=family_id,
			expires_at=now + timedelta(seconds=ttl),
			now=now,
			name=family_id,
		)
	return token


def rotate(refresh_token: str) -> tuple[str, str]:
	"""Consume a token once, preserving its family's original expiry.

	A second consumer of a used token is a replay, including a concurrent second
	request. Revoke the entire family durably before rejecting that consumer.
	"""
	token_hash = _token_hash(refresh_token)
	reused = None
	with _transaction() as db:
		record = _lock_token(db, token_hash)
		if record is None:
			raise frappe.AuthenticationError(_INVALID_TOKEN)

		now = now_datetime()
		if record.used_at:
			_revoke_family(db, record.family_id, now)
			reused = record
		else:
			if record.revoked_at or get_datetime(record.expires_at) <= now:
				raise frappe.AuthenticationError(_INVALID_TOKEN)
			_require_enabled_user(db, record.user)
			next_token, next_name = _insert_token(
				db,
				user=record.user,
				client_id=record.client_id,
				family_id=record.family_id,
				expires_at=record.expires_at,
				now=now,
			)
			db.sql(
				"""UPDATE `tabAPI Refresh Token`
				SET used_at = %s, replaced_by = %s, modified = %s
				WHERE name = %s""",
				(now, next_name, now, record.name),
			)

	if reused is not None:
		frappe.logger("api_auth").warning(
			"refresh_reused", extra={"user": reused.user, "family_id": reused.family_id}
		)
		raise frappe.AuthenticationError(_INVALID_TOKEN)
	return record.user, next_token


def revoke(refresh_token: str) -> None:
	"""Idempotently revoke the whole family without disclosing token validity.

	Unknown, expired, used and already-revoked well-shaped tokens all succeed.
	Malformed payloads are validation errors, not database queries.
	"""
	try:
		token_hash = _token_hash(refresh_token)
	except frappe.AuthenticationError:
		raise frappe.ValidationError(
			"refresh_token must be a nonempty string of at most 512 characters"
		) from None

	with _transaction() as db:
		record = _lock_token(db, token_hash)
		if record is not None:
			_revoke_family(db, record.family_id, now_datetime())


def _token_hash(token: str) -> str:
	if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
		raise frappe.AuthenticationError(_INVALID_TOKEN)
	try:
		encoded = token.encode("utf-8")
	except UnicodeEncodeError:
		raise frappe.AuthenticationError(_INVALID_TOKEN) from None
	return hashlib.sha256(encoded).hexdigest()


@contextmanager
def _transaction() -> Iterator[Database]:
	"""Use a dedicated READ COMMITTED transaction without swapping frappe.local.db.

	A fresh statement snapshot is required after a family-lock wait: Frappe's
	default snapshot/repeatable-read isolation can reject concurrent consumers
	instead of letting them observe the winner's committed token state.
	"""
	source = frappe.db
	db = get_db(
		socket=source.socket,
		host=source.host,
		port=source.port,
		user=source.user,
		password=source.password,
		cur_db_name=source.cur_db_name,
	)
	try:
		if db.db_type == "mariadb":
			db.sql("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
		db.begin()
		if db.db_type == "postgres":
			db.sql("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
		try:
			yield db
			db.commit()
		except BaseException:
			db.rollback()
			raise
	finally:
		db.close()


def _lock_token(db: Database, token_hash: str) -> frappe._dict | None:
	# This first lookup is intentionally non-locking: every operation must lock
	# the immutable root first, even when presenting a different descendant.
	matches = db.sql(
		"SELECT family_id FROM `tabAPI Refresh Token` WHERE token_hash = %s",
		(token_hash,),
		as_dict=True,
	)
	if not matches:
		return None

	family_id = matches[0].family_id
	root = db.sql(
		"SELECT name FROM `tabAPI Refresh Token` WHERE name = %s FOR UPDATE",
		(family_id,),
		as_dict=True,
	)
	if not root:
		return None

	# Re-read after obtaining the family lock so a waiting consumer observes
	# the winner's committed used_at/revoked_at under READ COMMITTED.
	records = db.sql(
		"""SELECT name, `user`, client_id, family_id, expires_at, used_at, revoked_at
		FROM `tabAPI Refresh Token` WHERE token_hash = %s FOR UPDATE""",
		(token_hash,),
		as_dict=True,
	)
	return records[0] if records else None


def _require_enabled_user(db: Database, user: str) -> None:
	if not isinstance(user, str) or user == "Guest":
		raise frappe.AuthenticationError(_INVALID_TOKEN)
	users = db.sql("SELECT enabled FROM `tabUser` WHERE name = %s", (user,), as_dict=True)
	if not users or not users[0].enabled:
		raise frappe.AuthenticationError(_INVALID_TOKEN)


def _insert_token(
	db: Database,
	*,
	user: str,
	client_id: str | None,
	family_id: str,
	expires_at: datetime,
	now: datetime,
	name: str | None = None,
) -> tuple[str, str]:
	token = secrets.token_urlsafe(48)
	name = name or secrets.token_hex(16)
	request = getattr(frappe.local, "request", None)
	ip_address = getattr(frappe.local, "request_ip", None)
	user_agent = request.headers.get("User-Agent") if request is not None else None
	db.sql(
		"""INSERT INTO `tabAPI Refresh Token`
		(name, creation, modified, owner, modified_by, docstatus, idx,
		token_hash, `user`, client_id, family_id, expires_at, ip_address, user_agent)
		VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, %s)""",
		(
			name,
			now,
			now,
			user,
			user,
			hashlib.sha256(token.encode("utf-8")).hexdigest(),
			user,
			client_id,
			family_id,
			expires_at,
			ip_address[:140] if ip_address else None,
			user_agent[:1024] if user_agent else None,
		),
	)
	return token, name


def _revoke_family(db: Database, family_id: str, now: datetime) -> None:
	db.sql(
		"""UPDATE `tabAPI Refresh Token` SET revoked_at = %s, modified = %s
		WHERE family_id = %s AND revoked_at IS NULL""",
		(now, now, family_id),
	)
