frappe.ui.form.on("API Settings", {
	refresh: function (frm) {
		frm.add_custom_button(__("Clear Old Logs Now"), function () {
			frappe.confirm(
				__("Are you sure you want to delete API Logs older than {0} days?", [
					frm.doc.retention_days || 30,
				]),
				function () {
					frm.call({
						doc: frm.doc,
						method: "clear_logs_now",
						freeze: true,
						freeze_message: __("Clearing old logs..."),
						callback: function (r) {
							if (!r.exc) {
								frappe.show_alert({
									message: __("Logs cleared successfully"),
									indicator: "green",
								});
							}
						},
					});
				},
			);
		});
	},
});
