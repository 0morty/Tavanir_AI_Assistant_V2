# Linux Host Filesystem & Permission Guide for Qdrant Bind Mounts

This document outlines the required filesystem permissions and directory setup when deploying **Qdrant** with host bind mounts on Linux hosts.

---

## The Root Cause: Container Non-Root UID

The official Qdrant Docker image (`qdrant/qdrant`) executes the Qdrant binary as a non-root system user with:
* **User ID (UID):** `1000`
* **Group ID (GID):** `1000`

When using Docker Compose with a host bind mount:
```yaml
volumes:
  - ${QDRANT_STORAGE_PATH:-./data/qdrant_storage}:/qdrant/storage
```

If the target host directory does not already exist when `docker compose up -d` is invoked, the **Docker daemon (running as root) automatically creates the directory owned by `root:root` with permissions `drwxr-xr-x`**.

When Qdrant attempts to initialize its storage segments, write-ahead logs (WAL), and RocksDB instances inside `/qdrant/storage`, it encounters an OS-level permission rejection:
```text
Error: Failed to initialize storage: Permission denied (os error 13)
```

---

## Production Setup Instructions (Linux Host)

Before launching the container on a Linux server, run the following commands to pre-create the storage directory and assign ownership to UID/GID `1000:1000`.

### 1. Default Repository-Contained Storage (`./data/qdrant_storage`)
If using the default local storage path within the repository root:

```bash
# 1. Create the host storage directory
mkdir -p ./data/qdrant_storage

# 2. Assign ownership to Qdrant's container user (1000:1000)
sudo chown -R 1000:1000 ./data/qdrant_storage

# 3. Ensure read, write, and execute permissions
chmod -R 750 ./data/qdrant_storage
```

### 2. Dedicated Production Mount Point (e.g. `/var/lib/tavanir/qdrant/storage`)
In production environments where persistent data is placed on a dedicated NVMe or high-speed block storage partition:

```bash
# 1. Create directory structure
sudo mkdir -p /var/lib/tavanir/qdrant/storage

# 2. Assign ownership to container UID/GID 1000:1000
sudo chown -R 1000:1000 /var/lib/tavanir/qdrant/storage

# 3. Restrict permissions so only the container user can read/write
sudo chmod 700 /var/lib/tavanir/qdrant/storage
```

Then configure `.env`:
```ini
QDRANT_STORAGE_PATH=/var/lib/tavanir/qdrant/storage
```

---

## Verification

To verify that the permissions are set correctly before running Docker Compose:

```bash
ls -ld ./data/qdrant_storage
# Expected output:
# drwxr-x--- 2 1000 1000 4096 ... ./data/qdrant_storage
```

Once confirmed, start the container:
```bash
docker compose up -d tavanir_qdrant
```
