// Mechanical exports of the operator-approved artwork; no new image generation.
// sharp is already supplied by the locked Next.js dependency tree.
const fs = require('node:fs/promises');
const path = require('node:path');
const sharp = require('sharp');

const ROOT = path.resolve(__dirname, '..');
const SOURCE = path.resolve(ROOT, '../assets/portal/app-icon-approved-20261008.png');
const ICON_DIRECTORY = 'public/icons/portal-20261008';
const PNG_TARGETS = [
  ...[16, 32, 48, 192, 512].map(size => ({
    file: `${ICON_DIRECTORY}/icon-${size}.png`, size, variant: 'any',
  })),
  ...[192, 512].map(size => ({
    file: `${ICON_DIRECTORY}/maskable-${size}.png`, size, variant: 'maskable',
  })),
  { file: `${ICON_DIRECTORY}/apple-touch-icon.png`, size: 180, variant: 'any' },
  // File-convention and legacy endpoints also receive the approved mark.
  { file: 'app/icon.png', size: 512, variant: 'any' },
  { file: 'app/apple-icon.png', size: 180, variant: 'any' },
  { file: 'public/icons/logo.png', size: 192, variant: 'any' },
];

async function renderPng(size, variant) {
  const metadata = await sharp(SOURCE).metadata();
  if (metadata.width !== metadata.height || metadata.hasAlpha) {
    throw new Error('The approved source must be square and opaque.');
  }
  let pipeline = sharp(SOURCE);
  if (variant === 'any') {
    // Remove background margin only, making the same mark clearer at 16/32px.
    const inset = Math.round(metadata.width * 0.10);
    pipeline = pipeline.extract({ left: inset, top: inset,
      width: metadata.width - inset * 2, height: metadata.height - inset * 2 });
  } else if (variant !== 'maskable') {
    throw new Error('Unknown icon variant.');
  }
  // The maskable export keeps all approved padding and its opaque background.
  return pipeline.resize(size, size, { kernel: 'lanczos3' })
    .png({ palette: true, colours: 64, quality: 90, dither: 0,
      compressionLevel: 9, effort: 10 }).toBuffer();
}

function encodeIco(frames) {
  const header = Buffer.alloc(6 + frames.length * 16);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(frames.length, 4);
  let offset = header.length;
  frames.forEach(({ size, data }, index) => {
    const entry = 6 + index * 16;
    header[entry] = size;
    header[entry + 1] = size;
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(data.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += data.length;
  });
  return Buffer.concat([header, ...frames.map(frame => frame.data)]);
}

async function main() {
  for (const target of PNG_TARGETS) {
    const destination = path.join(ROOT, target.file);
    await fs.mkdir(path.dirname(destination), { recursive: true });
    const data = await renderPng(target.size, target.variant);
    await fs.writeFile(destination, data);
    console.log(`${target.file}: ${target.size}x${target.size}, ${data.length} bytes`);
  }
  const frames = await Promise.all([16, 32, 48].map(async size => ({
    size, data: await renderPng(size, 'any'),
  })));
  const ico = encodeIco(frames);
  await fs.writeFile(path.join(ROOT, 'app/favicon.ico'), ico);
  console.log(`app/favicon.ico: 16/32/48px frames, ${ico.length} bytes`);
}

module.exports = { ROOT, SOURCE, PNG_TARGETS, renderPng, encodeIco };
if (require.main === module) main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
