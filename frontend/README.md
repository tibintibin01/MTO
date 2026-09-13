# MTO Public Treasury Portal (Next.js + PWA)

This is the public-facing side of the MTO Treasury Management System. It allows property owners and field assessors to securely check property status.

## Features
- **PWA Ready**: Installable on Android/iOS via "Add to Home Screen".
- **Responsive Design**: Works perfectly on mobile, tablet, and desktop.
- **Real-time Sync**: Proxies requests to the FastAPI backend.
- **Safe Offline Support**: Only the offline shell is available; property,
  payment, authentication, and admin data always require the live server.

## Setup
1. `cd frontend`
2. `npm ci`
3. `npm run dev`

## PWA Icons
The manifest references `/public/icons/icon-192x192.png` and `/public/icons/icon-512x512.png`.
Generate these from the official logo before deploying:
```bash
# Requires ImageMagick
mkdir -p frontend/public/icons
convert assets/official/logo.png -resize 192x192 frontend/public/icons/icon-192x192.png
convert assets/official/logo.png -resize 512x512 frontend/public/icons/icon-512x512.png
```
Or use any image editor to export the logo at those two sizes into `frontend/public/icons/`.

## Architecture
Built with Next.js 16 (App Router), React 19, Tailwind CSS, and Serwist.
It communicates with the backend via `/api/v1/` rewrites defined in `next.config.js`.
