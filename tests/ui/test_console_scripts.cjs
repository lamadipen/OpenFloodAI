const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '../../tools/console');
for (const file of fs.readdirSync(root)) {
  if (!/\.(html|js)$/.test(file)) continue;
  test(`console ${file}: scripts parse and local assets exist`, () => {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    if (file.endsWith('.js')) new vm.Script(source, { filename: file });
    else {
      for (const match of source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
        new vm.Script(match[1], { filename: file });
      }
      for (const match of source.matchAll(/(?:href|src)="\/console\/([^"?${]+)(?:\?[^"${]*)?"/g)) {
        assert.ok(fs.existsSync(path.join(root, match[1])), match[1]);
      }
    }
  });
}
