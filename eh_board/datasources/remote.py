"""Shared, bounded remote snapshots. Widget rendering never performs network I/O."""
from odoo import _

from .file import FileDataSource
from ..lib.registry import register_datasource


class RemoteSnapshotDataSource(FileDataSource):
    external = True
    tabular = True

    def validate(self, source):
        if not source.remote_last_success:
            return [_('No valid remote snapshot exists yet. Ask a Dashboard Administrator to refresh this source.')]
        return []

    def _status(self, source, result):
        state = source._remote_status()
        result["source_status"] = state
        if state["state"] == "stale":
            result["warning"] = _("Showing the last successful remote snapshot. Its scheduled refresh is overdue or failed.")
        return result

    def aggregate(self, source, spec):
        if not source.remote_last_success:
            result = {"rows": [], "dimensions": spec.get("dimensions", []),
                      "measures": spec.get("measure_keys", []), "measure_labels": spec.get("measure_labels", {})}
            result["error"] = self.validate(source)[0]
            return self._status(source, result)
        return self._status(source, super().aggregate(source, spec))

    def records(self, source, spec):
        return self._status(source, super().records(source, spec))

    def preview(self, source, limit=20):
        source._require_remote_admin()
        return source.tabular_rows()[:max(1, min(int(limit), 20))]


@register_datasource
class SheetsDataSource(RemoteSnapshotDataSource):
    key = "sheets"
    label = "Google Sheets"


@register_datasource
class RestDataSource(RemoteSnapshotDataSource):
    key = "rest"
    label = "REST / JSON"
