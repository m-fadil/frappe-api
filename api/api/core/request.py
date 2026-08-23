from __future__ import annotations

from typing import Any

import frappe


def get_request_data(kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
	"""Gabungkan kwargs pemanggil dengan `frappe.form_dict`.

	`frappe.app.make_form_dict` sudah mem-parse body request — JSON, form-urlencoded,
	maupun multipart — ke `form_dict`, lengkap dengan tipe aslinya, dan sudah menolak
	JSON rusak sebelum sampai ke sini. Mem-parse ulang `frappe.request.data` bikin
	body non-JSON (form-urlencoded, upload file) jadi 400 palsu.

	kwargs menang atas form_dict: frappe memanggil endpoint dengan `**form_dict` yang
	sudah difilter ke signature, jadi nilainya sama; yang beda hanya pemanggil manual
	dari Python yang memang harus menang.
	"""
	data = dict(kwargs or {})

	try:
		form_dict = dict(frappe.form_dict)
	except RuntimeError:
		# di luar request context frappe (background job / unit test tanpa init)
		form_dict = {}

	for key, value in form_dict.items():
		data.setdefault(key, value)

	data.pop("cmd", None)
	return data
