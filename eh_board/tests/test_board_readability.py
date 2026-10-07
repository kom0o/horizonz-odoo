# -*- encoding: utf-8 -*-
"""Real-browser regression for complete category labels and compact slicers."""
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "eh_board", "eh_board_readability")
class TestBoardReadability(HttpCase):

    def test_long_labels_and_compact_slicer(self):
        labels = [
            "000 Readability Station International Coastal Service Center Category %02d" % index
            for index in range(30)
        ]
        partners = self.env["res.partner"].create([
            {"name": label, "color": index + 1}
            for index, label in enumerate(labels)
        ])
        dashboard = self.env["eh.board.dashboard"].create({
            "name": "Readability regression", "state": "published",
            "group_ids": [(6, 0, [self.env.ref("eh_board.group_board_admin").id])],
        })
        source = self.env["eh.board.datasource"].create({
            "name": "Readability contacts", "provider_type": "orm",
            "model_id": self.env["ir.model"]._get("res.partner").id,
            "domain": repr([("id", "in", partners.ids)]),
        })
        measure = self.env["eh.board.measure"].create({
            "name": "Stations", "datasource_id": source.id, "aggregate": "count",
        })
        common = {
            "dashboard_id": dashboard.id, "datasource_id": source.id,
            "primary_dimension_id": self.env["ir.model.fields"]._get("res.partner", "name").id,
        }
        chart = self.env["eh.board.item"].create(dict(
            common, item_type="hbar", title="Complete station names", record_limit=0,
            measure_ids=[(6, 0, measure.ids)], sort_mode="label"))
        slicer = self.env["eh.board.item"].create(dict(
            common, item_type="slicer", title="Choose stations",
            chart_options={"slicer_display": "auto"}))
        self.env["eh.board.layout.version"].create({
            "dashboard_id": dashboard.id, "name": "Readability layout",
            "is_active": True, "is_default": True,
            "grid": {
                str(chart.id): {"x": 0, "y": 0, "w": 8, "h": 7},
                str(slicer.id): {"x": 8, "y": 0, "w": 4, "h": 5},
            },
        })
        action = self.env["ir.actions.client"].create({
            "name": "Readability regression", "tag": "eh_board.board",
            "params": {"dashboard_id": dashboard.id},
        })
        self.env.cr.flush()
        script = r"""
        (async () => {
            const expected = __LABELS__;
            const assert = (condition, message) => {
                if (!condition) throw new Error(message);
            };
            const waitFor = async (predicate, message) => {
                const deadline = performance.now() + 20000;
                while (performance.now() < deadline) {
                    if (predicate()) return;
                    await new Promise((resolve) => setTimeout(resolve, 50));
                }
                throw new Error('Timed out: ' + message);
            };
            const chart = () => document.querySelector('[data-item-type="hbar"] .eh_board_cartesian');
            const categoryLabels = () => Array.from(chart()?.querySelectorAll('.eh_board_cat_label') || []);
            const slicer = () => document.querySelector('[data-item-type="slicer"] .eh_board_slicer');
            const choices = () => Array.from(slicer()?.querySelectorAll('.eh_board_slicer_chip') || []);
            const filterCount = () => document.querySelectorAll('.eh_board_crossbar .eh_board_chip').length;
            await waitFor(() => chart() && slicer() && categoryLabels().length === 30 && choices().length >= 30,
                'both widgets to load');

            const inspectLabels = () => {
                const svg = chart().querySelector('svg');
                const rects = Array.from(chart().querySelectorAll('.eh_board_bar'));
                const plotStart = Math.min(...rects.map((rect) => Number(rect.getAttribute('x'))));
                const found = categoryLabels().map((label) => {
                    const lines = Array.from(label.querySelectorAll('tspan'));
                    const full = lines.map((line) => line.textContent).join(' ').replace(/\s+/g, ' ').trim();
                    assert(lines.length > 0, 'category must have visible text lines');
                    assert(full === label.getAttribute('aria-label'), 'visible lines must contain complete category name');
                    assert(!/[\u2026]/.test(full), 'category must not contain an ellipsis');
                    const box = label.getBBox();
                    assert(box.x >= -1, 'category must stay inside SVG left boundary');
                    assert(box.x + box.width <= plotStart - 2, 'category must stay inside its gutter');
                    assert(box.y >= -1 && box.y + box.height <= svg.viewBox.baseVal.height + 1,
                        'category must stay inside SVG vertical bounds');
                    return full;
                });
                assert(JSON.stringify(found.slice().sort()) === JSON.stringify(expected.slice().sort()),
                    'all 30 distinct station names must be visible in SVG text');
                return categoryLabels().reduce((sum, label) => sum + label.querySelectorAll('tspan').length, 0);
            };
            // Resize the actual element observed by ResizeObserver. This checks
            // browser geometry and live wrapping, not a detached helper function.
            // Native scrollbars consume client width inside the requested CSS width.
            chart().style.width = '400px';
            await waitFor(() => Math.abs(chart().querySelector('svg').viewBox.baseVal.width - chart().clientWidth) < 2,
                'narrow chart geometry');
            const narrowLines = inspectLabels();
            const narrowWidth = chart().getBoundingClientRect().width;
            assert(narrowLines > 30, 'narrow chart must wrap long station names');
            chart().style.width = '800px';
            await waitFor(() => Math.abs(chart().querySelector('svg').viewBox.baseVal.width - chart().clientWidth) < 2,
                'wide chart geometry');
            const wideLines = inspectLabels();
            assert(chart().getBoundingClientRect().width > narrowWidth + 300, 'chart must actually widen');
            assert(wideLines < narrowLines, 'wider tile must reduce wrapping while retaining all text');
            chart().style.removeProperty('width');

            const list = slicer().querySelector('.eh_board_slicer_chips');
            assert(slicer().classList.contains('o_compact'), '30 choices must select compact mode automatically');
            assert(list.getBoundingClientRect().height <= 181, 'compact list must stay at or below 180px plus rounding');
            assert(list.clientHeight > 0 && list.scrollHeight > list.clientHeight, 'choices must scroll inside bounded list');
            const search = async (value, count) => {
                await waitFor(() => slicer() && slicer().querySelector('input'), 'slicer after reload');
                const input = slicer().querySelector('input');
                input.value = value;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                await waitFor(() => choices().length === count && choices().every((choice) =>
                    choice.textContent.toLowerCase().includes(value.toLowerCase())), 'search results for ' + value);
                assert(slicer().classList.contains('o_compact'), 'search must not switch layout');
            };
            await search('000 Readability Station', 30);
            choices()[0].focus();
            const end = new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true });
            choices()[0].dispatchEvent(end);
            assert(end.defaultPrevented, 'End must be handled by compact list');
            assert(document.activeElement === choices()[29], 'End must focus last choice');
            assert(list.scrollTop > 0, 'keyboard focus must reveal last choice through scrolling');

            await search(expected[0], 1);
            choices()[0].click();
            await waitFor(() => categoryLabels().length === 1 && filterCount() === 1
                && choices()[0]?.getAttribute('aria-pressed') === 'true',
                'first selection to filter chart');
            assert(choices()[0].getAttribute('aria-pressed') === 'true', 'selected choice must expose pressed state');
            await search(expected[29], 1);
            choices()[0].click();
            await waitFor(() => categoryLabels().length === 2 && filterCount() === 2
                && choices()[0]?.getAttribute('aria-pressed') === 'true',
                'multiple selections to OR their chart filters');
            assert(slicer().querySelector('.eh_board_slicer_clear'), 'active list must offer Clear');
            slicer().querySelector('.eh_board_slicer_clear').click();
            await waitFor(() => categoryLabels().length === 30 && filterCount() === 0
                && choices()[0]?.getAttribute('aria-pressed') === 'false',
                'Clear to remove visible and search-hidden selections');
            assert(choices()[0].getAttribute('aria-pressed') === 'false', 'Clear must reset pressed state');
            await search('No matching station exists', 0);
            assert(slicer().querySelector('.eh_board_slicer_empty'), 'empty search must show an explicit result');
            await search('000 Readability Station', 30);
            assert(!document.querySelector('.eh_board_widget_error'), 'widgets must remain error-free');
            console.log('test successful');
        })().catch((error) => console.error(error));
        """.replace("__LABELS__", json.dumps(labels))
        self.browser_js(
            "/web#action=%s" % action.id, script,
            ready="!!document.querySelector('.eh_board_app')",
            login="admin", timeout=120,
        )
