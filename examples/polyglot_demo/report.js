// Demo fixture: a small Node.js utility with intentional issues.
// Used by the OpenSourceGuard multi-language demo and benchmark.

const crypto = require('crypto');

/**
 * Parse a CSV string into rows. Crashes on empty input: rows[0] is undefined
 * and `.split` throws, which is the bug the demo issue describes.
 */
function parseCsv(text) {
  const rows = text.split('\n').filter((line) => line.length > 0);
  return rows[0].split(',');
}

class ReportRenderer {
  constructor(target) {
    this.target = target;
  }

  render(untrustedHtml) {
    // Intentional finding: JS-INNERHTML (CWE-79)
    this.target.innerHTML = untrustedHtml;
  }

  buildToken() {
    // Intentional finding: JS-MATH-RANDOM-TOKEN (CWE-338)
    const token = Math.random().toString(36).slice(2);
    return token;
  }

  safeToken() {
    return crypto.randomUUID();
  }
}

const computeTotal = (values) => values.reduce((sum, value) => sum + value, 0);

module.exports = { parseCsv, ReportRenderer, computeTotal };
