# Approved portal app icon — 2026-10-08

The operator approved the generated gold roof / off-white D / sea-green accent design for the installed public website's PC taskbar and phone home-screen identity. The government seal remains inside the website header and footer. This is not a new municipal seal or an update to the Windows Treasury desktop application.

## Source and reproduction

- Built-in image-generation tool used; no fallback API/CLI or API key used.
- Approved, unaltered source: `assets/portal/app-icon-approved-20261008.png`, 1254×1254 opaque PNG.
- Source SHA256: `a29e4f790b57cbe2b04b9e866c390ceb8e44e8dafad38a7fe419f2425544bc00`.
- Export command: `cd frontend && node scripts/generate-portal-icons.cjs`.
- Validation command: `cd frontend && npm run test:icons`.
- Existing locked sharp dependency performs only mechanical margin cropping, resizing, palette encoding and ICO packaging. No runtime graphics code or new dependency is introduced.
- Icon contracts cover exact approved-source identity, output dimensions, opaque backgrounds, maskable safe area, ICO frames, versioned manifest/shortcut references, unchanged official seal, and a 350 KB aggregate PNG budget. Browser regressions also fetch each declared icon from a local production build and check its bytes and rendered Apple/browser metadata.

Final generation prompt:

> Use case: logo-brand. Asset type: one proposed app icon for the Dipaculao public property-tax web portal, used as an installed website's desktop taskbar icon and a mobile home-screen icon. Create ONE original professional icon asset, square 1024x1024, not a presentation sheet or a device mockup. Subject: a confident, minimal geometric property-roof symbol integrated with a subtle capital D monogram for Dipaculao. A warm gold roof caps a bold off-white D-shaped architectural form, with a restrained sea-green accent in the negative space. Make it a single coherent mark rather than a house illustration plus a letter. It should feel like a trustworthy modern civic digital service, not a real-estate sales logo or a cryptocurrency/payment brand. Palette: full-bleed opaque deep navy #0B2636 background, warm gold #EFCB83 roof, soft off-white #F5F7F2 main mark, sea-green #2B8273 small accent. Style: premium flat vector-like raster logo, crisp edges, balanced optical weight, generous negative space, strong silhouette recognizable at tiny taskbar sizes. All meaningful symbol parts must lie within a centered circle of diameter 68 percent of the image; background fills every edge, square corners, no pre-applied rounded-corner tile. No wording, no slogans, no tiny letters other than the integrated D concept, no official seals or emblems, no peso symbols, no shields, no stars, no rings or ornamental borders, no photorealism, no textures, no gradients, no bevels, no 3D, no lighting effects, no shadows, no watermark. Render the final single icon straight-on.

The model returned 1254×1254; exports use actual decoded dimensions rather than assuming the prompt dimensions.

## Asset and metadata coverage

- Versioned regular PNGs: 16, 32, 48, 192 and 512px in `frontend/public/icons/portal-20261008/`.
- Separate opaque maskable PNGs: 192 and 512px, retaining all source padding; foreground checked against the centered 40%-radius safe circle.
- Apple touch PNG: 180px.
- Next.js file-convention endpoints `app/icon.png` and `app/apple-icon.png` contain the same approved design.
- `app/favicon.ico` packages 16/32/48px PNG frames.
- Legacy `/icons/logo.png` now contains the approved mark for compatibility; the official `/dipaculao-logo.png` and other seal files remain untouched.
- Manifest icon/shortcut URLs are versioned so installed browsers can detect a change. Application name, start URL, scope and standalone identity are unchanged.

References: [maskable safe area](https://web.dev/articles/maskable-icon), [Next.js icon conventions](https://nextjs.org/docs/app/api-reference/file-conventions/metadata/app-icons), [Chrome app-update behavior](https://developer.chrome.com/blog/improvements-to-web-app-updates).

## Deployment boundary and caveats

Local verification: production build PASS; icon contracts 69 PASS (141,525 total PNG bytes); public lookup/metadata/browser regressions 98 PASS; property-workspace contracts 80 PASS; synthetic publication tests 184 PASS; audit-policy tests 11 PASS. Lint has zero errors and the same six pre-existing staff-page warnings. Dependency audit has zero production findings and no blocking findings; the existing development-only build risk remains unchanged, due for review on 2026-10-14. Remote CI and deployed-asset verification are required before calling publication complete.

CI portability repair: the first Linux run passed the PNG pixel checks but failed the ICO frame's compressed-byte comparison. The ICO test now checks format, actual dimensions, directory bounds and exact decoded RGBA pixels rather than platform-dependent PNG encoding bytes. No asset, safe-area, source-identity, budget, security or production code check is bypassed.

Website-only PR and checked deployment. No office/server activation, version/tag change, financial calculation change, credentials change, scheduled publisher change or certification change. The website does not require a Windows Treasury installer or server CMD command.

New installations use the published assets. Existing installed app icons are controlled by the user's browser/OS and may retain the older icon until their app metadata updates or the shortcut is recreated. Do not claim that a hard refresh forces every OS-level taskbar or home-screen icon to change. A regular Chrome/Edge browser window can still show the browser's own taskbar icon; the branded taskbar icon is for the website installed as an app. Physical iPhone/Android installation cannot be proved by a desktop viewport simulation.
