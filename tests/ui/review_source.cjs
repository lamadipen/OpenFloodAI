// The review page is split across review.js, review-charts.js, review-sam.js and review-onion.js.
// Tests slice functions out of the page script by marker text, so this rebuilds the page as one
// document with a single inline script, in the same order the browser loads the files.
const fs = require("node:fs");
const path = require("node:path");

const consoleDir = path.join(__dirname, "../../tools/console");
const FILES = ["review.js", "review-charts.js", "review-sam.js", "review-onion.js"];

function reviewHtml() {
  const page = fs.readFileSync(path.join(consoleDir, "review.html"), "utf8");
  const start = page.indexOf('<script src="/console/review.js"></script>');
  if (start < 0) throw new Error("review.html no longer loads review.js");
  const script = FILES.map((name) => fs.readFileSync(path.join(consoleDir, name), "utf8")).join("\n");
  return `${page.slice(0, start)}<script>\n${script}\nmain();\n</script>\n</body>\n</html>\n`;
}

module.exports = { reviewHtml, FILES };
