# MTO Public Treasury Portal (Next.js + PWA)

This is the public-facing side of the MTO Treasury Management System. It allows property owners and field assessors to securely check property status.

## Features
- **PWA Ready**: Installable on Android/iOS via "Add to Home Screen".
- **Responsive Design**: Works perfectly on mobile, tablet, and desktop.
- **Real-time Sync**: Proxies requests to the FastAPI backend.
- **Offline Support**: Basic property data is cached for field work.

## Setup
1. `cd frontend`
2. `npm install`
3. `npm run dev`

## Architecture
Built with Next.js 14 (App Router), Tailwind CSS, and `next-pwa`.
It communicates with the backend via `/api/v1/` rewrites defined in `next.config.js`.
