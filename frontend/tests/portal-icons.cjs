const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');
const sharp = require('sharp');
const { ROOT, SOURCE, PNG_TARGETS, renderPng } = require('../scripts/generate-portal-icons.cjs');
let passed = 0;
function check(value, message) { assert.ok(value, message); passed++; }
function digest(data) { return createHash('sha256').update(data).digest('hex'); }

(async () => {
  check(digest(await fs.readFile(SOURCE)) ===
    'a29e4f790b57cbe2b04b9e866c390ceb8e44e8dafad38a7fe419f2425544bc00',
  'The user-approved source artwork is preserved exactly.');
  let totalBytes = 0;
  for (const target of PNG_TARGETS) {
    const data = await fs.readFile(path.join(ROOT, target.file));
    totalBytes += data.length;
    const metadata = await sharp(data).metadata();
    check(metadata.format === 'png' && metadata.width === target.size &&
      metadata.height === target.size, `${target.file}: genuine PNG and correct dimensions`);
    const { data: pixels, info } = await sharp(data).ensureAlpha().raw()
      .toBuffer({ resolveWithObject: true });
    let foreground = 0;
    let unsafe = 0;
    let transparent = 0;
    for (let y = 0; y < info.height; y++) for (let x = 0; x < info.width; x++) {
      const index = (y * info.width + x) * 4;
      if (pixels[index + 3] !== 255) transparent++;
      // The navy background is below these channels; white/gold/green are not.
      if (pixels[index] > 90 || pixels[index + 1] > 110) {
        foreground++;
        const radius = Math.hypot(x + 0.5 - info.width / 2, y + 0.5 - info.height / 2);
        if (radius > info.width * 0.4) unsafe++;
      }
    }
    check(transparent === 0, `${target.file}: opaque full-bleed background`);
    check(foreground > info.width * info.height * 0.08, `${target.file}: nonblank approved mark`);
    if (target.variant === 'maskable') {
      check(unsafe === 0, `${target.file}: mark fits the circular 40%-radius safe area`);
    }
    const expected = await sharp(await renderPng(target.size, target.variant))
      .ensureAlpha().raw().toBuffer();
    check(pixels.equals(expected), `${target.file}: exact mechanical export of approved source`);
  }
  check(totalBytes < 350000, 'All PNG exports together remain below 350 KB.');
  const ico = await fs.readFile(path.join(ROOT, 'app/favicon.ico'));
  check(ico.readUInt16LE(0) === 0 && ico.readUInt16LE(2) === 1 &&
    ico.readUInt16LE(4) === 3, 'Valid ICO directory with three frames.');
  for (let index = 0; index < 3; index++) {
    const entry = 6 + index * 16;
    const size = [16, 32, 48][index];
    const length = ico.readUInt32LE(entry + 8);
    const offset = ico.readUInt32LE(entry + 12);
    const frame = ico.subarray(offset, offset + length);
    check(ico[entry] === size && ico[entry + 1] === size &&
      offset >= 54 && offset + length <= ico.length, `ICO ${size}px directory bounds`);
    // PNG compression/container bytes can vary across libvips platform builds.
    // The actual dimensions, format and every decoded RGBA pixel must match.
    const frameMetadata = await sharp(frame).metadata();
    const framePixels = await sharp(frame).ensureAlpha().raw().toBuffer();
    const expectedPixels = await sharp(await renderPng(size, 'any'))
      .ensureAlpha().raw().toBuffer();
    check(frameMetadata.format === 'png' && frameMetadata.width === size &&
      frameMetadata.height === size && framePixels.equals(expectedPixels),
    `ICO ${size}px approved PNG pixels and dimensions`);
  }
  const manifest = JSON.parse(await fs.readFile(path.join(ROOT, 'public/manifest.json'), 'utf8'));
  check(manifest.name === 'Public Treasury Web Portal' &&
    manifest.start_url === '/' && manifest.scope === '/' && manifest.display === 'standalone',
  'Installed application identity, scope, start URL and standalone behavior unchanged.');
  for (const purpose of ['any', 'maskable']) for (const size of [192, 512]) {
    const icon = manifest.icons.find(item => item.purpose === purpose && item.sizes === `${size}x${size}`);
    check(icon && icon.type === 'image/png' && icon.src.startsWith('/icons/portal-20261008/'),
      `${purpose} ${size}px icon uses a versioned asset URL`);
    check(PNG_TARGETS.some(target => `/` + target.file.replace(/^public\//, '') === icon.src &&
      target.size === size && target.variant === (purpose === 'any' ? 'any' : 'maskable')),
    `${purpose} ${size}px manifest dimensions and purpose match its asset`);
  }
  check(manifest.icons.every(icon => ['any', 'maskable'].includes(icon.purpose)),
    'Regular and maskable purposes are separate, not a combined padding compromise.');
  check(manifest.shortcuts[0].icons[0].src === '/icons/portal-20261008/icon-192.png',
    'Search shortcut uses the new app mark.');
  const layout = await fs.readFile(path.join(ROOT, 'app/layout.tsx'), 'utf8');
  check(layout.includes('/icons/portal-20261008/apple-touch-icon.png') &&
    layout.includes('180x180') && !layout.includes('/icons/logo.png'),
  'Apple/browser metadata points to approved, versioned exports.');
  const shell = await fs.readFile(path.join(ROOT, 'app/components/PublicShell.tsx'), 'utf8');
  check(shell.includes('src="/dipaculao-logo.png"'), 'Official seal retained in the site header.');
  check(digest(await fs.readFile(path.join(ROOT, 'public/dipaculao-logo.png'))) ===
    '3b89dd66415c164d23864cc86265f401de6adc24d5724b1a209a42c985073d66',
  'Official seal bytes unchanged.');
  console.log(`PORTAL APP ICON CONTRACTS: PASS (${passed} checks; ${totalBytes} PNG bytes)`);
})().catch(error => { console.error(error.message); process.exitCode = 1; });
