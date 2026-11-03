// Actual dependency consumers, small synthetic files and bounded regressions.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { createRequire } = require('node:module');
const ROOT = path.resolve(__dirname, '..');

module.exports = async function testGlobSecurity() {
  let checks = 0;
  const check = (value, message) => { assert.ok(value, message); checks++; };
  const manifest = require(path.join(ROOT, 'package.json'));
  const lock = require(path.join(ROOT, 'package-lock.json'));
  const legacy = require('minimatch');
  const modern = require('minimatch-modern');
  check(manifest.overrides.glob === '14.0.2', 'Exact patched glob pin');
  check(manifest.overrides['minimatch@<4'] === '$minimatch', 'Explicit legacy adapter');
  check(manifest.overrides['minimatch@>=4'] === '11.0.1', 'Exact patched modern pin');
  check(lock.packages['vendor/minimatch-legacy-compat'].dev === true, 'Adapter remains development only');
  for (const [entry, item] of Object.entries(lock.packages)) {
    if (entry.endsWith('node_modules/glob')) check(item.version === '14.0.2', 'Every glob copy patched: ' + entry);
    if (entry.endsWith('node_modules/minimatch') || entry.endsWith('node_modules/minimatch-modern')) {
      if (entry === 'node_modules/minimatch') check(item.link === true && item.resolved === 'vendor/minimatch-legacy-compat', 'Reviewed legacy source only');
      else check(item.version === '11.0.1' && Boolean(item.integrity), 'Every engine copy patched and integrity pinned: ' + entry);
    }
  }
  for (const name of ['eslint', '@eslint/config-array', '@eslint/eslintrc', 'eslint-plugin-import', 'eslint-plugin-react', 'eslint-plugin-jsx-a11y']) {
    const consumer = createRequire(require.resolve(name));
    check(consumer('minimatch') === legacy && typeof legacy === 'function', 'Actual legacy consumer resolves callable adapter: ' + name);
  }
  const fromSerwist = createRequire(require.resolve('@serwist/next'));
  const glob = fromSerwist('glob');
  check(fromSerwist('glob/package.json').version === '14.0.2', 'Actual Serwist resolves patched glob');
  const fromGlob = createRequire(fromSerwist.resolve('glob'));
  check(fromGlob('minimatch/package.json').version === '11.0.1', 'Actual glob resolves patched modern engine');
  const cases = [
    ['app/page.tsx', '**/*.tsx', {}, true], ['app/page.ts', '**/*.tsx', {}, false],
    ['.hidden.ts', '*.ts', {}, false], ['.hidden.ts', '*.ts', { dot: true }, true],
    ['app/PAGE.tsx', '**/*.TSX', { nocase: true }, true],
    ['app/page.tsx', '*.tsx', { matchBase: true }, true],
    ['app/page.tsx', '*.tsx', {}, false], ['app/a.js', '**/*.{js,ts}', {}, true],
    ['Button', 'B*', {}, true], ['Input', 'B*', {}, false],
    ['src/a.ts', 'src/+(a|b).ts', {}, true], ['src/c.ts', 'src/+(a|b).ts', {}, false],
    ['x', '!x', {}, false], ['y', '!x', {}, true],
  ];
  for (const [value, pattern, options, expected] of cases) {
    for (const api of [legacy, modern.minimatch]) check(api(value, pattern, options) === expected, 'Matching contract: ' + pattern);
    check(new legacy.Minimatch(pattern, options).match(value) === expected, 'Class contract: ' + pattern);
    check(legacy.makeRe(pattern, options).test(value) === expected, 'Import-linter tester: ' + pattern);
    check(new legacy.Minimatch(pattern, options).makeRe().test(value) === expected, 'Class tester: ' + pattern);
  }
  assert.deepEqual(['a.ts', 'b.js'].filter(legacy.filter('*.ts')), ['a.ts']); checks++;
  assert.deepEqual(legacy.match(['a.ts', 'b.js'], '*.js'), ['b.js']); checks++;
  assert.deepEqual(legacy.braceExpand('a{1,2}.ts'), ['a1.ts', 'a2.ts']); checks++;
  const defaults = legacy.defaults({ nocase: true });
  check(defaults('A.TS', '*.ts'), 'Callable defaults');
  check(defaults.makeRe('*.ts').test('A.TS'), 'Tester defaults');
  check(new defaults.Minimatch('*.ts').makeRe().test('A.TS'), 'Class defaults');
  check(new (legacy.Minimatch.defaults({ nocase: true }))('*.ts').match('A.TS'), 'Static class defaults');
  check(defaults.defaults({ dot: true })('.A.TS', '*.ts'), 'Nested defaults');
  check(Object.isFrozen(legacy.makeRe('*.ts')), 'Tester cannot become a mutable regex fallback');
  const { Linter } = require('eslint');
  const linter = new Linter();
  const ruleConfig = {
    languageOptions: { ecmaVersion: 2022, sourceType: 'module' },
    plugins: { import: require('eslint-plugin-import') },
    rules: { 'import/no-internal-modules': ['error', { forbid: ['pkg/private/**'] }] },
  };
  const denied = linter.verify("import value from 'pkg/private/file';", ruleConfig);
  check(denied.length === 1 && denied[0].ruleId === 'import/no-internal-modules', 'Real import-linter makeRe consumer rejects forbidden module');
  check(linter.verify("import value from 'pkg/public';", ruleConfig).length === 0, 'Real import-linter permits allowed module');
  // Upstream bounded-preprocessing regression. Never invoke the vulnerable engine.
  for (const api of [legacy, modern.minimatch, fromGlob('minimatch').minimatch]) {
    const mm = new api.Minimatch(Array(30).fill('**/../a/b').join('/'), { optimizationLevel: 2, braceExpandMax: 64 });
    check(mm.set.length === 64, 'Pattern amplification stops at the explicit budget');
    let comparisons = 0;
    mm.partsMatch = () => { comparisons++; return false; };
    const many = Array.from({ length: 1001 }, (_, i) => ['x' + i]);
    check(mm.secondPhasePreProcess(many) === many && comparisons === 0, 'Large sets skip quadratic deduplication');
  }
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mto-glob-compat-'));
  try {
    for (let i = 0; i < 4; i++) {
      fs.mkdirSync(path.join(root, 'dir' + i));
      fs.writeFileSync(path.join(root, 'dir' + i, 'a.txt'), 'synthetic');
    }
    check(glob.globSync('**/*.txt', { cwd: root }).length === 4, 'Normal Serwist-style sync traversal');
    check((await glob.glob('**/*.txt', { cwd: root })).length === 4, 'Normal async traversal');
    const controller = new AbortController();
    const reason = new Error('SYNTHETIC_ABORT');
    let reads = 0;
    const customFS = { readdir(dir, options, callback) {
      reads++;
      fs.readdir(dir, options, (error, entries) => {
        controller.abort(reason);
        callback(error, entries);
      });
    } };
    await assert.rejects(glob.glob('**/*.txt', { cwd: root, signal: controller.signal, fs: customFS }), error => error === reason); checks++;
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
    check(reads === 1, 'Cancellation does not launch post-abort directory traversal');
  } finally {
    // Only this freshly created synthetic tree is removed; never office data.
    if (path.dirname(path.resolve(root)) !== path.resolve(os.tmpdir()) || !path.basename(root).startsWith('mto-glob-compat-')) throw Error('Unsafe synthetic cleanup target');
    fs.rmSync(root, { recursive: true });
  }
  console.log(JSON.stringify({ status: 'PASS', checks, scope: 'Patched glob/minimatch, actual legacy consumers, bounded preprocessing, abort traversal and unchanged matching contracts' }));
};
