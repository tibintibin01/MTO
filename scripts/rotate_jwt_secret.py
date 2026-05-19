#!/usr/bin/env python3
"""
MTO Treasury — JWT Secret Rotation Utility (#6 / #16)
Run this script to generate a new high-entropy JWT secret.
Replace MTO_JWT_SECRET in your .env (local) and GitHub Actions Secrets (CI/CD).

Usage:
    python rotate_jwt_secret.py
"""
import secrets

new_secret = secrets.token_urlsafe(64)
print("=" * 70)
print("NEW JWT SECRET (copy this to .env and GitHub Actions Secrets):")
print("=" * 70)
print(f"\nMTO_JWT_SECRET={new_secret}\n")
print("Steps:")
print("  1. Update .env:             Replace MTO_JWT_SECRET=<old> with the above")
print("  2. Update GitHub Secrets:   Settings > Secrets > MTO_JWT_SECRET")
print("  3. Restart the API server — existing tokens will be invalidated (re-login required)")
print("  4. Notify active users if this is a production rotation")
print("=" * 70)
