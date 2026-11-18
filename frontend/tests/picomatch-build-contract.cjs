// Test the installed build callers with ordinary repository matching only.
const assert = require('node:assert/strict');
const { realpathSync } = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');

module.exports = function verifyPicomatchBuildContract() {
  const root = path.resolve(__dirname, '..');
  const fork = realpathSync(path.join(root, 'vendor/picomatch-4-guarded'));
  const lock = require('../package-lock.json').packages;
  const pins = Object.entries(lock).filter(([key, item]) =>
    key.endsWith('node_modules/picomatch') || item.name === 'picomatch');
  assert.ok(pins.length);
  for (const [key, item] of pins) {
    assert.equal(item.link, true, key);
    assert.equal(item.resolved, 'vendor/picomatch-4-guarded', key);
  }
  assert.equal(lock['vendor/picomatch-4-guarded'].dev, true);

  const fromTinyglobby = createRequire(require.resolve('tinyglobby'));
  const callers = [
    ...['anymatch', 'micromatch', 'readdirp', 'tinyglobby'].map(name =>
      [name, createRequire(require.resolve(name))]),
    ['fdir', createRequire(fromTinyglobby.resolve('fdir'))],
  ];
  for (const [name, fromCaller] of callers) {
    const manifest = fromCaller.resolve('picomatch/package.json');
    assert.equal(realpathSync(path.dirname(manifest)), fork, name);
    assert.equal(fromCaller('picomatch/package.json').version, '4.0.7+mto.1', name);
    const match = fromCaller('picomatch');
    assert.equal(match('{app,components}/**/*.{ts,tsx}')('app/lookup/page.tsx'), true, name);
    assert.equal(match('{app,components}/**/*.{ts,tsx}')('vendor/testing.cjs'), false, name);
    assert.equal(match('**/*.ts', { ignore: '**/*.d.ts' })('components/types.d.ts'), false, name);
    assert.equal(match(['*.ts', '*.tsx'])('page.tsx'), true, name);
  }

  const match = require('picomatch');
  const simpleExtendedGroup = '@(app|components)/*.tsx';
  const opts = { noext: false, noextglob: false };
  // An ordinary (non-repeating) extended group is intentionally unsupported.
  assert.throws(() => match(simpleExtendedGroup, opts), SyntaxError);
  assert.throws(() => match.parse(simpleExtendedGroup, opts), SyntaxError);
  assert.throws(() => match.makeRe(simpleExtendedGroup, opts), SyntaxError);
  assert.throws(() => require('picomatch/posix')(simpleExtendedGroup, opts), SyntaxError);
  const parse = require('picomatch/lib/parse');
  assert.throws(() => parse.fastpaths(simpleExtendedGroup, opts), SyntaxError);
  assert.equal(match.makeRe('**/*.tsx').test('app/page.tsx'), true);
  assert.equal(require('micromatch').isMatch('app/page.tsx', '**/*.{js,tsx}'), true);
  assert.equal(require('anymatch')('**/*.ts', 'app/route.ts'), true);
  console.log(JSON.stringify({ status: 'PASS', callers: callers.map(([name]) => name), developmentOnly: true }));
};
