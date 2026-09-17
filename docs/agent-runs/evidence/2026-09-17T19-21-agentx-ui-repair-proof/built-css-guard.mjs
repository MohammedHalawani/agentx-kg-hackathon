import { readFileSync, readdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const distDir = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', 'frontend', 'dist', 'assets');
const file = readdirSync(distDir).find((f) => f.endsWith('.css'));
if (!file) throw new Error('No built CSS in dist/assets');
const css = readFileSync(join(distDir, file), 'utf8');

const forbidden = /\.text-muted\{color:var\(--muted\)\}/.test(css);
const expected = /\.text-muted\{color:var\(--muted-foreground\)\}/.test(css);
const rootIdx = css.lastIndexOf(':root{--background');
const darkIdx = css.lastIndexOf('.dark{--color-surface');

console.log(JSON.stringify({
  cssFile: file,
  forbiddenTextMuted: forbidden,
  correctTextMuted: expected,
  darkAfterRoot: darkIdx > rootIdx,
  pass: !forbidden && expected && darkIdx > rootIdx,
}, null, 2));

if (forbidden || !expected || darkIdx <= rootIdx) process.exit(1);
