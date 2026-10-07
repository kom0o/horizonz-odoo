/** @odoo-module **/
/* ERP Heritage - Dashboard Builder
 * The client-side item-type registry - mirror of the Python registry. A new
 * item type is registered here by key; BoardItem resolves the component by the
 * meta.component the server returns. No switch, no god-component. */

import { registry } from "@web/core/registry";
import { CartesianChart } from "./charts/cartesian_chart";
import { PieChart } from "./charts/pie_chart";
import { KpiTile, GaugeChart } from "./charts/kpi_tile";
import { ListWidget, ContentWidget } from "./charts/list_widget";
import { RadarChart, FunnelChart, ScatterChart, PolarChart, RadialChart, RoseChart, BulletChart, HeatmapChart } from "./charts/more_charts";
import { MapChart } from "./charts/map_chart";
import { PivotWidget } from "./charts/pivot_widget";
import { SlicerWidget } from "./charts/slicer_widget";
import { DecompWidget } from "./charts/decomp_widget";

const items = registry.category("eh_board_items");

items.add("bar", CartesianChart);
items.add("line", CartesianChart);
items.add("pie", PieChart);
items.add("tile", KpiTile);
items.add("kpi", KpiTile);
items.add("gauge", GaugeChart);
items.add("list", ListWidget);
items.add("richtext", ContentWidget);
items.add("todo", ContentWidget);
items.add("radar", RadarChart);
items.add("funnel", FunnelChart);
items.add("scatter", ScatterChart);
items.add("polar", PolarChart);
items.add("radial", RadialChart);
items.add("rose", RoseChart);
items.add("map", MapChart);
items.add("bullet", BulletChart);
items.add("heatmap", HeatmapChart);
items.add("pivot", PivotWidget);
items.add("slicer", SlicerWidget);
items.add("decomp", DecompWidget);
