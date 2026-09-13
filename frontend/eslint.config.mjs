import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';

export default defineConfig([
  ...nextVitals,
  {
    // Existing portal code predates these React Compiler-oriented rules.
    // Keep the security upgrade reviewable; remediate these legacy findings
    // in a dedicated UI refactor instead of mixing behavior changes here.
    rules: {
      '@next/next/no-html-link-for-pages': 'off',
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/static-components': 'off',
    },
  },
  globalIgnores([
    '.next/**',
    'out/**',
    'build/**',
    'next-env.d.ts',
    'public/sw.js',
    'public/swe-worker-*.js',
  ]),
]);
