'use strict';

const upstream = require('minimatch-modern').minimatch;

// minimatch 11 deliberately no longer compiles regexes. Existing import-linter
// consumers only use makeRe(...).test(path); preserve that operation by calling
// the patched matcher, never by restoring the vulnerable regex engine.
const tester = matcher => Object.freeze({ test: value => matcher.match(value) });
function callable(base) {
  const match = (value, pattern, options) => base(value, pattern, options);
  Object.assign(match, base);
  match.Minimatch = class Minimatch extends base.Minimatch {
    makeRe() { return tester(this); }
    static defaults(options) { return callable(base.defaults(options)).Minimatch; }
  };
  match.makeRe = (pattern, options) => tester(new match.Minimatch(pattern, options));
  match.defaults = options => callable(base.defaults(options));
  return match;
}
module.exports = callable(upstream);
