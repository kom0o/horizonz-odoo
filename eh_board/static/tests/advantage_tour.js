/** @odoo-module **/
/* Native DOM workflows; business reads and writes use real authenticated RPC. */
window.ehBoardAdvantageTour = async function (scenario, data) {
    const visible = (node) => !!(node && node.getClientRects().length);
    const waitFor = async (predicate, label) => {
        const deadline = Date.now() + 25000;
        while (Date.now() < deadline) {
            const result = predicate();
            if (result) {
                await new Promise((resolve) => requestAnimationFrame(resolve));
                if (predicate()) return result;
            }
            await new Promise((resolve) => setTimeout(resolve, 50));
        }
        throw new Error(`Timed out waiting for ${label}`);
    };
    const button = (root, text) => [...root.querySelectorAll('button')].find(
        (node) => visible(node) && node.textContent.trim() === text);
    const click = async (root, text) => {
        const node = await waitFor(() => button(root, text), `button ${text}`);
        if (node.disabled) throw new Error(`Button ${text} is disabled`);
        node.click();
        await new Promise((resolve) => requestAnimationFrame(resolve));
    };
    const set = (node, value, event = 'change') => {
        if (!node) throw new Error('Missing form control');
        node.value = value;
        node.dispatchEvent(new Event(event, { bubbles: true }));
    };
    const field = (root, label) => [...root.querySelectorAll('label')].find(
        (node) => node.childNodes[0]?.textContent.trim() === label)?.querySelector('input, select, textarea');
    const menu = async (text) => {
        document.querySelector('.eh_board_menubtn').click();
        await click(document.querySelector('.eh_board_header'), text);
    };
    const modal = (node) => node.closest('.modal') || node.closest('.o_dialog');
    await waitFor(() => document.querySelector('.eh_board_app .eh_board_widget'), 'mounted board');
    if (scenario === 'scorecard') {
        await menu('KPI scorecard');
        let card = await waitFor(() => document.querySelector('.eh_board_scorecard'), 'scorecard dialog');
        await waitFor(() => card.textContent.includes('No scorecard yet'), 'empty scorecard');
        await click(card, 'Edit scorecard');
        await click(card, 'Add objective');
        let objective = await waitFor(() => card.querySelector('.eh_scorecard_node'), 'objective editor');
        set(field(objective, 'Title'), 'Contact coverage', 'input');
        set(field(objective, 'Effective from'), data.day);
        set(field(objective, 'Effective through'), data.day);
        await click(objective, 'Add child metric');
        const metric = await waitFor(() => card.querySelectorAll('.eh_scorecard_node')[1], 'child metric editor');
        set(field(metric, 'Title'), 'Contact goal', 'input');
        set(field(metric, 'Metric widget'), String(data.itemId));
        set(field(metric, 'Zero-score baseline'), '0', 'input');
        set(field(metric, 'Full-score target'), '6', 'input');
        if (!button(modal(card), 'Save scorecard')?.disabled) throw new Error('Unpreviewed targets must disable Save');
        const period = card.querySelector('.eh_scorecard_toolbar select');
        await waitFor(() => period.querySelectorAll('option').length > 1, 'new effective period');
        set(period, `${data.day}/${data.day}`);
        await waitFor(() => card.getAttribute('aria-busy') === 'false' && card.querySelectorAll('.eh_scorecard_score').length === 2,
            'calculated child and group scores');
        if ([...card.querySelectorAll('.eh_scorecard_score')].some((node) => node.textContent.trim() !== '50 / 100')) {
            throw new Error('Three contacts against target six must score 50 for child and group');
        }
        await click(modal(card), 'Save scorecard');
        await waitFor(() => !!button(card, 'Edit scorecard') && !button(modal(card), 'Save scorecard'), 'saved read view');
        await click(modal(card), 'Close');
        await waitFor(() => !document.querySelector('.eh_board_scorecard'), 'closed scorecard');
        await menu('KPI scorecard');
        card = await waitFor(() => document.querySelector('.eh_board_scorecard'), 'reopened scorecard');
        await waitFor(() => card.querySelectorAll('.eh_scorecard_node').length === 2, 'persisted hierarchy');
        set(card.querySelector('.eh_scorecard_toolbar select'), `${data.day}/${data.day}`);
        await waitFor(() => card.querySelectorAll('.eh_scorecard_score').length === 2, 'reloaded scores');
        if (!card.textContent.includes('Contact coverage') || !card.textContent.includes('Contact goal')) {
            throw new Error('Saved names did not survive reopening');
        }
    } else if (scenario === 'query') {
        await menu('Compare two models');
        const query = await waitFor(() => document.querySelector('.o_eh_query_builder'), 'query builder');
        set(query.querySelector('.eh-query-name'), 'Contact comparison', 'input');
        for (const side of ['left', 'right']) {
            const section = query.querySelector(`[data-side="${side}"]`);
            const input = section.querySelector('.o-autocomplete--input');
            input.focus();
            set(input, data.modelName, 'input');
            const option = await waitFor(() => [...document.querySelectorAll('.o-autocomplete--dropdown-item')].find(
                (node) => visible(node) && node.textContent.trim() === data.modelName), `${side} model choice`);
            option.click();
            const key = await waitFor(() => {
                const select = section.querySelector('.eh-query-key');
                return select && [...select.options].some((row) => row.value === 'country_id') ? select : null;
            }, `${side} fields`);
            set(key, 'country_id');
            section.querySelector('.eh-query-add-filter').click();
            const filter = await waitFor(() => section.querySelector('.eh-query-filter'), `${side} filter`);
            set(filter.querySelector('.eh-query-filter-field'), 'name');
            await new Promise((resolve) => requestAnimationFrame(resolve));
            set(filter.querySelector('[aria-label="Filter operator"]'), 'ilike');
            set(filter.querySelector('.eh-query-filter-value'), 'Advantage fixture', 'input');
        }
        set(query.querySelector('.eh-query-formula'), 'a / b', 'input');
        const dialog = modal(query);
        await waitFor(() => !dialog.querySelector('.eh-query-preview-button').disabled, 'complete query');
        dialog.querySelector('.eh-query-preview-button').click();
        await waitFor(() => query.querySelector('.eh-query-preview tbody tr') && !dialog.querySelector('.eh-query-save-button').disabled,
            'query calculation preview');
        const numbers = [...query.querySelectorAll('.eh-query-preview tbody tr:first-child td')].slice(2).map((cell) => Number(cell.textContent));
        if (JSON.stringify(numbers) !== '[3,3,1]') throw new Error(`Expected grouped counts 3,3 and ratio1, got ${numbers}`);
        set(query.querySelector('.eh-query-name'), 'Reviewed contact comparison', 'input');
        await waitFor(() => query.querySelector('.eh-query-stale') && dialog.querySelector('.eh-query-save-button').disabled, 'stale query blocked');
        dialog.querySelector('.eh-query-preview-button').click();
        await waitFor(() => !query.querySelector('.eh-query-stale') && !dialog.querySelector('.eh-query-save-button').disabled, 'updated query preview');
        dialog.querySelector('.eh-query-save-button').click();
        await waitFor(() => !document.querySelector('.o_eh_query_builder'), 'saved query dialog closed');
        await waitFor(() => document.querySelectorAll('.eh_board_app .eh_board_widget').length === 2 &&
            document.querySelector('.eh_board_app').textContent.includes('Reviewed contact comparison'), 'query widget mounted');
    } else {
        throw new Error(`Unknown scenario ${scenario}`);
    }
    console.log('test successful');
};
