frappe.listview_settings["API Log"] = {
	get_indicator: function (doc) {
		const code = parseInt(doc.status_code, 10) || 200;
		if (code >= 500) {
			return [__("Error (5xx)"), "red", "status_code,>=,500"];
		} else if (code >= 400) {
			return [__("Client Error (4xx)"), "orange", "status_code,>=,400|status_code,<,500"];
		} else {
			return [__("Success (2xx)"), "green", "status_code,<,400"];
		}
	},
};
