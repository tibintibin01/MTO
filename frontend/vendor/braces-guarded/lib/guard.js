'use strict';

// Local build-only remediation for GHSA-vfj7-8cjw-p6xm. These fixed bounds
// cannot be disabled by options. The original normal-pattern algorithms remain.
const MAX_DEPTH = 64;
const MAX_NODES = 30000;

const assertDepth = depth => {
  if (depth > MAX_DEPTH) {
    throw new SyntaxError('MTO_BRACES_MAX_DEPTH: pattern/AST nesting exceeds 64 levels');
  }
};

const assertTree = ast => {
  // Iterative preflight BEFORE any recursive walker. Only child-node edges
  // are traversed: normal parser ASTs deliberately have parent/prev backlinks.
  const pending = [[ast, 0]];
  const seen = new WeakSet();
  let count = 0;
  while (pending.length) {
    const [node, depth] = pending.pop();
    if (node === null || typeof node !== 'object' || Array.isArray(node)) {
      throw new TypeError('MTO_BRACES_INVALID_AST: expected an AST node');
    }
    assertDepth(depth);
    if (seen.has(node)) {
      throw new SyntaxError('MTO_BRACES_CYCLIC_AST: child nodes must form a tree');
    }
    seen.add(node);
    if (++count > MAX_NODES) {
      throw new SyntaxError('MTO_BRACES_MAX_NODES: AST exceeds 30000 nodes');
    }
    if (node.nodes !== undefined) {
      if (!Array.isArray(node.nodes)) {
        throw new TypeError('MTO_BRACES_INVALID_AST: nodes must be an array');
      }
      if (node.nodes.length > MAX_NODES - count) {
        throw new SyntaxError('MTO_BRACES_MAX_NODES: AST exceeds 30000 nodes');
      }
      for (let i = node.nodes.length - 1; i >= 0; i--) {
        pending.push([node.nodes[i], depth + 1]);
      }
    }
  }
};

module.exports = {assertDepth, assertTree, MAX_DEPTH, MAX_NODES};
