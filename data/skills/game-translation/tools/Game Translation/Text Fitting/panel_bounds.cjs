/* Painted-panel containment. Pure geometry/pixel readers; no game or API needed.
 * Rectangles are half-open. Predicates and margins must be calibrated per widget.
 * Browser/NW: GameTranslationPanelBounds. Node: require('./panel_bounds.cjs').
 */
(function(root) {
  'use strict';
  function rect(value, label = 'rectangle') {
    if (!value || !['left', 'top', 'right', 'bottom'].every(k => Number.isFinite(value[k])) ||
        value.right <= value.left || value.bottom <= value.top) {
      throw new Error('Missing, empty or invalid ' + label);
    }
    return value;
  }
  function pixelBounds(image, predicate) {
    const {width, height, data} = image;
    if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0 ||
        !data || data.length !== width * height * 4 || typeof predicate !== 'function') {
      throw new Error('Expected complete RGBA image data and a pixel predicate');
    }
    let left = width, top = height, right = -1, bottom = -1;
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      if (predicate(data[i], data[i + 1], data[i + 2], data[i + 3], x, y)) {
        left = Math.min(left, x); top = Math.min(top, y);
        right = Math.max(right, x); bottom = Math.max(bottom, y);
      }
    }
    if (right < 0) throw new Error('Pixel predicate selected no pixels');
    return {left, top, right: right + 1, bottom: bottom + 1};
  }
  function transformRect(value, matrix) {
    rect(value);
    if (!matrix || !['a', 'b', 'c', 'd', 'tx', 'ty'].every(k => Number.isFinite(matrix[k])) ||
        matrix.a === 0 || matrix.d === 0 || matrix.b !== 0 || matrix.c !== 0) {
      throw new Error('Expected a nonzero axis-aligned affine transform; rotation/skew needs polygon containment');
    }
    const xs = [value.left, value.right].map(x => x * matrix.a + matrix.tx);
    const ys = [value.top, value.bottom].map(y => y * matrix.d + matrix.ty);
    return {left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys)};
  }
  function measure(panel, ink, minimum = 0) {
    rect(panel, 'painted panel'); rect(ink, 'text ink');
    if (!Number.isFinite(minimum) || minimum < 0) throw new Error('Invalid minimum margin');
    const margins = {left: ink.left - panel.left, right: panel.right - ink.right,
      top: ink.top - panel.top, bottom: panel.bottom - ink.bottom};
    return {margins, pass: Object.values(margins).every(v => v >= minimum)};
  }
  function evaluateReport(report, minimum, expectedCases, {allowMissingHealth = false} = {}) {
    if (!report || !Array.isArray(report.rows) || !report.rows.length) throw new Error('No observed cases');
    if (!Number.isInteger(expectedCases) || expectedCases <= 0) throw new Error('Declare the expected case count');
    if (typeof report.engineError !== 'string' && !(allowMissingHealth && report.engineError === undefined)) throw new Error('Missing native engine-error observation');
    const rows = report.rows.map(row => ({map: row.map, profile: row.profile, index: row.index,
      ...measure(row.panel, row.displayed, minimum)}));
    const identities = rows.map(r => JSON.stringify([r.map, r.profile, r.index]));
    if (rows.some(r => !Number.isInteger(r.map) || typeof r.profile !== 'string' || !Number.isInteger(r.index)) ||
        new Set(identities).size !== rows.length) throw new Error('Missing or duplicate case identity');
    return {cases: rows.length, expectedCases, failures: rows.filter(r => !r.pass).length,
      engineError: report.engineError ?? null, engineErrorObserved: typeof report.engineError === 'string',
      pass: rows.length === expectedCases && !report.engineError && rows.every(r => r.pass),
      minimumMargins: Object.fromEntries(['left', 'right', 'top', 'bottom'].map(k => [k, Math.min(...rows.map(r => r.margins[k]))])),
      rows};
  }
  const api = {pixelBounds, transformRect, measure, evaluateReport};
  // NW.js can expose both a DOM global and CommonJS in the same script context.
  root.GameTranslationPanelBounds = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
    if (require.main === module) {
      try {
        const args = process.argv.slice(2);
        if (args.length === 1 && args[0] === '--help') {
          console.log('node panel_bounds.cjs REPORT.json --margin PIXELS --expect-cases N [--allow-missing-health]\nRecomputes containment from recorded native rectangles, ignoring stored pass/margins. The optional flag permits old geometry-only observations without claiming engine health. This is evidence replay, not a new native run.');
        } else {
          if (![5, 6].includes(args.length) || args[1] !== '--margin' || args[3] !== '--expect-cases' || (args.length === 6 && args[5] !== '--allow-missing-health')) throw new Error('Use --help');
          const report = JSON.parse(require('fs').readFileSync(args[0], 'utf8').replace(/^\uFEFF/, ''));
          const result = evaluateReport(report, Number(args[2]), Number(args[4]), {allowMissingHealth: args.length === 6});
          const {rows, ...summary} = result;
          console.log(JSON.stringify(summary, null, 2)); process.exitCode = result.pass ? 0 : 1;
        }
      } catch (error) { console.error(String(error)); process.exitCode = 2; }
    }
  }
})(globalThis);
