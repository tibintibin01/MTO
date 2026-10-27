// Patched dependency contracts with synthetic data and loopback HTTP only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { createRequire } = require('node:module');
const ROOT = path.resolve(__dirname, '..');
const manifest = require(path.join(ROOT, 'package.json'));
const lock = require(path.join(ROOT, 'package-lock.json'));
const fromSerwist = createRequire(require.resolve('@serwist/next'));
const fromBlob = createRequire(require.resolve('@vercel/blob'));
let checks = 0;
function check(value, message) { assert.ok(value, message); checks++; }

async function main() {
  check(manifest.dependencies.next === '16.4.3', 'Reviewed Next.js patch');
  check(manifest.devDependencies['eslint-config-next'] === '16.4.3', 'Matching lint package');
  check(manifest.dependencies['@serwist/next'] === '9.5.12' && manifest.devDependencies.serwist === '9.5.12', 'No Serwist downgrade or unrelated upgrade');
  for (const [name, version] of Object.entries({ undici: '6.29.1', zod: '4.6.6' })) {
    check(manifest.overrides[name] === version, 'Explicit patched override: ' + name);
    const copies = Object.entries(lock.packages).filter(([entry]) => entry.endsWith('node_modules/' + name));
    check(copies.length > 0, 'Dependency remains present: ' + name);
    for (const [entry, item] of copies) check(item.version === version, 'Every nested copy patched: ' + entry);
  }
  check(fromSerwist('zod/package.json').version === '4.6.6', 'Serwist resolves patched Zod');
  check(fromBlob('undici/package.json').version === '6.29.1', 'Blob SDK resolves patched Undici');

  // Upstream Zod regression: bounds are checked BEFORE per-element parsing.
  const { z } = fromSerwist('zod');
  for (const kind of ['array', 'set', 'map']) {
    let parsed = 0;
    const value = z.string().refine(() => { parsed++; return true; });
    const schema = kind === 'array' ? z.array(value).max(2)
      : kind === 'set' ? z.set(value).max(2) : z.map(value, value).max(2);
    const input = kind === 'array' ? ['a', 'b', 'c']
      : kind === 'set' ? new Set(['a', 'b', 'c']) : new Map([['a', 'a'], ['b', 'b'], ['c', 'c']]);
    const result = schema.safeParse(input);
    check(!result.success && result.error.issues.length === 1, 'Oversized ' + kind + ' rejects with bounded issues');
    check(parsed === 0, 'Oversized ' + kind + ' does not visit elements');
    const valid = kind === 'array' ? ['a'] : kind === 'set' ? new Set(['a']) : new Map([['a', 'b']]);
    check(schema.safeParse(valid).success, 'Normal ' + kind + ' still validates');
  }

  // Upstream Undici regression: excessive encodings plus an early close must
  // reject normally, not leave an orphan stream that crashes the Node process.
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { 'Content-Encoding': 'gzip, gzip, gzip, gzip, gzip, gzip', 'Content-Length': '100' });
    res.end('x');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const { fetch } = fromBlob('undici');
    await assert.rejects(fetch('http://127.0.0.1:' + server.address().port), TypeError);
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
    check(true, 'Fetch rejects safely without an unhandled stream error');
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
  const config = require(path.join(ROOT, 'next.config.js'));
  check(typeof config.webpack === 'function', 'Serwist still wraps the Next.js webpack configuration');
  const worker = fs.readFileSync(path.join(ROOT, 'app/sw.ts'), 'utf8');
  check(worker.includes('runtimeCaching: [sensitiveNetworkOnly, ...defaultCache]'), 'Sensitive API routes remain network-only before general caching');
  console.log(JSON.stringify({ status: 'PASS', checks, scope: 'Patched dependency resolution, bounded Zod validation, loopback Undici error handling and unchanged Serwist privacy contract' }));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
