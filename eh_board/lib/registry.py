# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Item-type and datasource registries - the extensibility moat.

Every dashboard item type is a small class registered here, not a branch in a
giant ``if/elif`` ladder. Adding a chart or a KPI touches one Python class and
one OWL component; nothing in the models changes. The same idea backs the
datasource providers (ORM aggregation, joins, safe SQL, external feeds), so a
new data path plugs in without editing the item model.

This module holds no Odoo model. It is pure Python so it can be imported by
models, tests, and tooling without a database.
"""

# --------------------------------------------------------------------------
# Item types
# --------------------------------------------------------------------------

ITEM_TYPES = {}


class BoardItemType:
    """Base strategy for a dashboard item (a tile, chart, table, pivot...).

    Subclasses set ``key`` and override :meth:`build`. The model delegates every
    per-type decision here, so the item model itself carries no type-specific
    branching.
    """

    key = None                 # stable technical key, e.g. "bar", "kpi", "pivot"
    label = None               # human label shown in the type picker
    category = "chart"         # chart | kpi | table | pivot | content
    icon = "fa-chart-bar"      # font-awesome hint for the picker
    min_size = (3, 4)          # minimum grid cells (w, h)
    default_size = (4, 6)      # default grid cells (w, h)
    needs_measure = True       # requires at least one measure
    needs_dimension = True     # requires a primary dimension
    allow_secondary = True     # supports a secondary group-by dimension
    js_component = None        # registry key of the paired OWL component (defaults to key)

    def component(self):
        return self.js_component or self.key

    # -- data ---------------------------------------------------------------
    def build(self, item, options):
        """Return a JSON-serialisable payload for the OWL component.

        ``item`` is an ``eh.board.item`` record; ``options`` is the resolved
        runtime option dict (filters already merged into the domain). Must
        aggregate through the item's datasource - never ``search`` + a Python
        loop, never raw ``cr.execute`` for an ORM source.
        """
        raise NotImplementedError(
            "Item type %r must implement build()" % (self.key,))

    # -- validation ---------------------------------------------------------
    def validate(self, item):
        """Return a list of human diagnostics, empty when the item is sound.

        Surfaced inline on the widget so a misconfigured item explains itself
        instead of rendering a silent blank.
        """
        ds = getattr(item, "datasource_id", None)
        prov = get_datasource(ds.provider_type) if ds else None
        if ds and ds.provider_type in ("join", "sql"):
            # These providers carry their own measures/shape (join config, SQL
            # columns); the item's measure/dimension requirements do not apply.
            return prov.validate(ds) if prov else []
        if prov and getattr(prov, "tabular", False):
            # File / REST: measures + group-by come from parsed columns, so the
            # ir.model.fields checks below do not apply. Add friendly guidance.
            problems = prov.validate(ds)
            if self.needs_dimension and not item.primary_column_id:
                problems.append("Pick a column to group by.")
            if self.needs_measure and not item.measure_ids:
                problems.append("Add at least one measure column.")
            return problems
        problems = []
        if self.needs_measure and not item.measure_ids:
            problems.append("Add at least one measure.")
        if self.needs_dimension and not item.primary_dimension_id.sudo():
            problems.append("Pick a dimension to group by.")
        problems.extend(self.field_store_problems(item))
        return problems

    @staticmethod
    def field_store_problems(item):
        """Reject non-stored (computed) fields, which cannot be aggregated in SQL.

        This turns an ORM ``ValueError`` deep in ``_read_group`` into a plain
        message on the widget - the "errors that teach" contract.
        """
        problems = []
        for dim in (item.primary_dimension_id.sudo(), item.secondary_dimension_id.sudo()):
            if dim and not dim.store:
                problems.append(
                    "The group-by field '%s' is computed and cannot be "
                    "aggregated; choose a stored field."
                    % (dim.field_description or dim.name))
        for measure in item.measure_ids:
            if measure.field_id.sudo() and not measure.field_id.sudo().store:
                problems.append(
                    "The measure field '%s' is computed and cannot be "
                    "aggregated; choose a stored field."
                    % (measure.field_id.sudo().field_description or measure.field_id.sudo().name))
        return problems

    # -- serialization ------------------------------------------------------
    def serialize_extra(self, item):
        """Extra per-type fields to include in export/import.

        Returning them declaratively here means the JSON round-trip can never
        drift as new fields appear.
        """
        return {}


def register_item_type(cls):
    """Class decorator: register an item type by its ``key``."""
    if not cls.key:
        raise ValueError("Item type %r has no key" % (cls,))
    ITEM_TYPES[cls.key] = cls()
    return cls


def get_item_type(key):
    return ITEM_TYPES.get(key)


def item_type_selection():
    """Selection list for the item model, ordered by category then label."""
    order = {"kpi": 0, "chart": 1, "table": 2, "pivot": 3, "content": 4}
    rows = sorted(
        ITEM_TYPES.values(),
        key=lambda t: (order.get(t.category, 9), t.label or t.key),
    )
    return [(t.key, t.label or t.key) for t in rows]


# --------------------------------------------------------------------------
# Datasource providers
# --------------------------------------------------------------------------

DATASOURCES = {}


class BoardDataSource:
    """Base strategy for a data provider.

    ``aggregate`` returns grouped rows for a measure/dimension spec. External
    providers force ``read_only`` True and can never disable record rules.
    """

    key = None                 # orm | join | sql | file | rest | replica
    label = None
    read_only = True           # external providers may not override to False
    external = False           # True for out-of-Odoo sources (needs a credential)
    tabular = False            # True for column-based sources (file / REST feeds)

    def aggregate(self, source, spec):
        """Return ``(groups, meta)`` for a resolved aggregation spec.

        ``source`` is the ``eh.board.datasource`` record; ``spec`` is a plain
        dict (domain, group-bys, granularity, measures). Implementations must
        push work to the database, not load-all-and-loop.
        """
        raise NotImplementedError(
            "Datasource %r must implement aggregate()" % (self.key,))

    def validate(self, source):
        return []

    def preview(self, source, limit=20):
        return []

    def records(self, source, spec):
        """Return bounded raw rows for a record-list widget.

        Providers without a native row model reject this mode explicitly. This
        avoids pretending an aggregate SQL/join result is a set of editable
        business records.
        """
        return {
            "rows": [], "columns": [],
            "error": "Individual-record lists are not supported by this data source.",
        }


def register_datasource(cls):
    if not cls.key:
        raise ValueError("Datasource %r has no key" % (cls,))
    DATASOURCES[cls.key] = cls()
    return cls


def get_datasource(key):
    return DATASOURCES.get(key)


def datasource_selection():
    rows = sorted(DATASOURCES.values(), key=lambda d: d.label or d.key)
    return [(d.key, d.label or d.key) for d in rows]
