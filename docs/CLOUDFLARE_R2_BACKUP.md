# Cloudflare R2 Database Backup Runbook

This runbook configures the dedicated, private R2 destination for encrypted
database backups. It does not enable scheduled/live uploads. Activation is a
separate Phase 3 decision after a controlled encrypted restore test.

## Safety boundary

- R2 database-backup credentials are separate from receipt/document storage.
- The R2 token is limited to one backup bucket.
- Raw SQL is never uploaded. Cloud objects are `.sql.gz.enc` plus a signed
  `.manifest.json` file.
- Credentials and the encryption key are stored in the protected machine vault
  at `C:\ProgramData\MTO\secrets.json`, not in Git or the project `.env` file.
- The machine vault is shared by Administrator setup commands and the Windows
  SYSTEM API task, with access restricted to SYSTEM and Administrators.
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

### Existing Phase 2/3 installations created before the machine-vault update

Older releases stored R2 settings under the interactive Administrator profile,
while the automatic API task ran as Windows SYSTEM. After pulling this update,
migrate the already-verified vault once from an Administrator Command Prompt:

```bat
cd /d C:\MTO
call venv\Scripts\activate
python scripts\migrate_r2_vault.py
```

The migration fails closed on missing Phase 3 evidence or conflicting machine
settings. It never displays secret values, writes the machine vault atomically,
and restricts its Windows ACL. A successful Phase 3 attestation is preserved;
do not repeat the restore test unless the migration reports an error or the R2
destination/encryption key has changed.

## Recovery-key rule

Do not paste credentials or the recovery key into chat, email, GitHub, or a
shared document. Without the recovery key, encrypted R2 backups cannot be
restored. Anyone who obtains both an encrypted backup and that key can decrypt
municipal data.

## 6. Run the controlled Phase 3 recovery test

Phase 3 is deliberately separate from routine backups. It uses the newest
local `.sql` backup by default and performs this complete chain:

1. Verify the local SHA-256 checksum when its sidecar file is present.
2. Compress and encrypt the SQL dump with AES-256-GCM.
3. Upload only the encrypted artifact and signed manifest under `backups/`.
4. Download both objects into an isolated temporary directory.
5. Authenticate and decrypt the artifact and verify the original checksum.
6. Restore the recovered SQL into a randomly named temporary database.
7. Confirm the required tables and live property/payment row counts.
8. Drop the temporary database and delete all temporary local files.

This test never restores over the live MTO database. A checksum-only or
skipped restore is a Phase 3 failure.

Before running it, obtain a dedicated MariaDB/MySQL verification account from
the database administrator. This is a database account, not an MTO user shown
under User Management. It must be able to create and drop only the temporary
verification databases used by the test. Do not use the `mto_app` account and
do not run the MTO application as `root`.

On the MTO server, leave the USB recovery key disconnected and run:

```bat
cd /d C:\MTO
call venv\Scripts\activate
python scripts\verify_r2_backup_restore.py
```

The command asks for the verification database username and password if they
are not already in the protected vault. It then requires the exact confirmation:

```text
RESTORE TEST
```

If the full restore succeeds, the command records a Phase 3 attestation bound
to the current R2 endpoint, bucket, object prefix, and encryption key. Changing
any of those values invalidates the attestation and blocks future cloud uploads
until Phase 3 passes again.

The final prompt offers activation. Type this exact phrase only after the
restore success message is displayed:

```text
ACTIVATE CLOUD BACKUP
```

Pressing Enter instead records the successful recovery test but keeps live
cloud copies disabled.

After activation, restart the MTO API so it reloads the protected vault. Then
run one Hybrid Backup from System Settings and confirm all of the following:

- The local backup succeeds.
- The cloud status reports a successful upload.
- R2 contains one `.sql.gz.enc` object and its `.manifest.json` partner under
  `backups/`.
- No readable `.sql` object exists in R2.

## Phase 3 failure behavior

Any failure leaves automatic cloud backup disabled. The encrypted test object
may remain in R2 because the seven-day bucket lock correctly prevents its
early deletion; the 30-day lifecycle rule will eventually remove it.

Common blockers are:

- The verification database credentials are not MariaDB/MySQL credentials.
- The account cannot create or drop an isolated test database.
- `mysql.exe` cannot be found; set `MTO_MYSQL_PATH` to its full path.
- The local SQL file is incomplete or no longer matches its checksum.
- The uploaded object or signed manifest does not match after download.

Do not set `MTO_ENABLE_CLOUD_BACKUP=true` manually to bypass a failure. The
application also requires the Phase 3 attestation, so manual activation alone
cannot start cloud uploads.
