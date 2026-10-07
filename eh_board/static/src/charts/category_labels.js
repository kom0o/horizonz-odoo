/** @odoo-module **/
/* Full category labels shared by the screen and exported SVG. */

let measureContext;

export function categoryLabelWidth(value) {
    const text = String(value == null ? "" : value);
    if (measureContext === undefined) {
        measureContext = typeof document !== "undefined"
            ? document.createElement("canvas").getContext("2d") : null;
    }
    if (measureContext) {
        measureContext.font = '11px "DM Sans", sans-serif';
        // A small allowance also covers font substitution while fonts load.
        return measureContext.measureText(text).width * 1.08;
    }
    // Deterministic fallback for headless rendering, including wide CJK glyphs.
    return Array.from(text).reduce((width, char) => width
        + (/\s/.test(char) ? 4 : /[ilI.,'`:;]/.test(char) ? 4
            : /[MW@\u2e80-\uffff]/.test(char) ? 11 : 7), 0);
}

/** Wrap words and unbroken identifiers without replacing any text by ellipses. */
export function wrapCategoryLabel(value, maxWidth) {
    const text = String(value == null ? "" : value).trim();
    if (!text) return [""];
    const width = Math.max(12, maxWidth);
    const lines = [];
    let line = "";
    for (const word of text.split(/\s+/u)) {
        const joined = line ? `${line} ${word}` : word;
        if (categoryLabelWidth(joined) <= width) {
            line = joined;
            continue;
        }
        if (line) lines.push(line);
        line = "";
        // Graphemes keep emoji and combining accents intact at line breaks.
        const chars = typeof Intl.Segmenter === "function"
            ? Array.from(new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(word),
                (part) => part.segment)
            : Array.from(word);
        for (const char of chars) {
            if (line && categoryLabelWidth(line + char) > width) {
                lines.push(line);
                line = "";
            }
            line += char;
        }
    }
    if (line) lines.push(line);
    return lines.length ? lines : [""];
}
