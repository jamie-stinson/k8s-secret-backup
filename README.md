# 🔐 k8s-secrets-backup

Back up and restore Kubernetes secrets to any S3-compatible storage service (e.g., Backblaze B2, MinIO, AWS S3).  
Designed to run **inside Kubernetes** as a CronJob, ensuring secrets are safely backed up and easily restored when needed.

---

## ⚙️ Environment Variables

| Variable              | Required | Default                 | Description                                                                                   |
|-----------------------|----------|-------------------------|-----------------------------------------------------------------------------------------------|
| `NAMESPACES`          | Yes      | —                       | Comma-separated list of Kubernetes namespaces to back up or restore. Example: `default,kube-system` |
| `S3_BUCKET_NAME`       | Yes      | —                       | Name of the S3 bucket where backups will be stored                                            |
| `S3_BACKUP_DIR`       | No       | `k8s-secrets-backup`    | Folder/path prefix inside the bucket to organize backups                                     |
| `S3_ENDPOINT_URL`     | No       | —                       | Custom S3 endpoint URL (e.g., Backblaze: `https://s3.us-west-001.backblazeb2.com`)             |
| `S3_ACCESS_KEY_ID`    | Yes      | —                       | Access key for S3-compatible storage                                                          |
| `S3_SECRET_ACCESS_KEY`| Yes      | —                       | Secret key for S3-compatible storage                                                          |
| `RESTORE_MODE`        | No       | `false`                 | Set to `"true"` to run in restore mode instead of backup.                                     |
| `FORCE_OVERWRITE`     | No       | `false`                 | When restoring, overwrite existing secrets if `"true"`; else skip if secret already exists   |

---
