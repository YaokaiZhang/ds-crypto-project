// Resolve the frontend's existing dependencies without a second node_modules tree.
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../../apps/frontend/package.json', import.meta.url));
const ts = require('typescript');
export const asUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
export function transpile(path) {
  return ts.transpileModule(readFileSync(new URL(`../../apps/frontend/src/${path}`, import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
  }).outputText;
}
export async function load(path) {
  return import(asUrl(transpile(path)));
}
