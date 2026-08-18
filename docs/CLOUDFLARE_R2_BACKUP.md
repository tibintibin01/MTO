# Cloudflare R2 Database Backup Runbook

This runbook configures the dedicated, private R2 destination for encrypted
database backups. It does not enable scheduled/live uploads. Activation is a
separate Phase 3 decision after a controlled encrypted restore test.

## Safety boundary

- R2 database-backup credentials are separate from receipt/document storage.
- The R2 token is limited to one backup bucket.
- Raw SQL is never uploaded. Cloud objects are `.sql.gz.enc` plus a signed
  `.manifest.json` file.
- Credentials and the encryption key are stored in `~/.mto/secrets.json`, not
  in Git or the project `.env` file.
- `MTO_ENABLE_CLOUD_BACKUP` remains `0` throughout Phase 2.

## 1. Create the private Standard bucket

In **Cloudflare Dashboard → R2 Object Storage → Overview**:

1. Select **Create bucket**.
2. Use `mto-treasury-backups` (or another approved lowercase name).
3. Select the **Standard** storage class so the R2 free tier applies.
4. Do not enable public access, `r2.dev`, or a custom domain.

Official reference: <https://developers.cloudflare.com/r2/buckets/create-buckets/>

## 2. Add deletion protection and fallback retention

Open the new bucket and select **Settings**.

Create this bucket lock rule:

- Name: `protect-new-backups-7d`
- Prefix: `backups/`
- Retention: 7 days

This prevents newly created backups from being deleted prematurely. The
application normally retains 14 complete backup sets, so routine rotation
occurs after this minimum protection period. If backups are run unusually
often and the lock prevents rotation, the application fails closed and keeps
the verified local backup.

Create this lifecycle rule as a provider-side fallback:

- Name: `expire-old-backups-30d`
- Prefix: `backups/`
- Action: Delete after 30 days

The application enforces the tighter 14-set and 8 GiB limits. The 30-day rule
protects against abandoned objects if application rotation stops working.

Official references:

- <https://developers.cloudflare.com/r2/buckets/bucket-locks/>
- <https://developers.cloudflare.com/r2/buckets/object-lifecycles/>

## 3. Create the least-privilege R2 credential

From **R2 Overview**, select **Manage API Tokens** and create an account token:

- Permission: **Object Read & Write**
- Bucket scope: **Apply to specific buckets only**
- Selected bucket: the private MTO backup bucket

Do not choose Admin Read & Write and do not grant access to all buckets. Copy
the **Access Key ID** and **Secret Access Key** when Cloudflare displays them;
the secret cannot be displayed again.

Official reference: <https://developers.cloudflare.com/r2/api/tokens/>

## 4. Configure the MTO server securely

After pulling the Phase 2 update on the backend server:

```bat
cd /d C:\MTO
call venv\Scripts\activate
python scripts\configure_r2_backup.py
```

The utility asks for:

- Cloudflare Account ID
- Private bucket name
- Access Key ID and Secret Access Key (both hidden)
- A path for the offline recovery-key file, preferably on a removable USB
  drive kept separately from the server

The utility rejects recovery-key paths inside `C:\MTO` to prevent accidental Git commits.

It uploads only 64 random bytes under `phase2-probe/`, verifies create, read,
list, and delete permissions, deletes the probe, and then stores the secrets.
No taxpayer or database data is used during this test.

The utility never prints either R2 credential or the encryption key. It prints
only a non-secret key fingerprint that can be used to confirm key custody.

## 5. Re-check Phase 2 readiness

This command repeats the random probe without changing configuration:

```bat
python scripts\configure_r2_backup.py --check
```

Expected result:

```text
R2 backup bucket readiness check passed; live backup state was unchanged.
```

Restart the API after configuration so it reloads the secrets vault. The
System Administration screen must still show cloud backup as disabled until
Phase 3 is approved.

## Recovery-key rule

Do not paste credentials or the recovery key into chat, email, GitHub, or a
shared document. Without the recovery key, encrypted R2 backups cannot be
restored. Anyone who obtains both an encrypted backup and that key can decrypt
municipal data.
