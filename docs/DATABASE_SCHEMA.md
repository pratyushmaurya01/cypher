# Database Schema: Cypher Relational Store

The relational database (PostgreSQL in production, SQLite in local testing) stores authentication credentials, user profiles, and repository ownership/lifecycle metadata. Graph topologies remain isolated in Neo4j.

---

## 1. Entity-Relationship Diagram

```
+------------------------------------+          +------------------------------------+
|               users                |          |        repository_metadata         |
+------------------------------------+          +------------------------------------+
| id             VARCHAR(64) [PK]    | 1      N | repository_id   VARCHAR(64) [PK]   |
| email          VARCHAR(255) [UQ]   |--------<| owner_id        VARCHAR(64) [FK]   |
| hashed_password VARCHAR(255)       |          | name            VARCHAR(255)       |
| created_at     DATETIME            |          | storage_path    VARCHAR(512)       |
| updated_at     DATETIME            |          | status          VARCHAR(32)        |
+------------------------------------+          | snapshot_version INTEGER           |
                                                | error_message   TEXT               |
                                                | created_at      DATETIME           |
                                                | updated_at      DATETIME           |
                                                +------------------------------------+
```

---

## 2. Table Specifications

### 2.1 `users` Table
Stores registered platform accounts and authentication hashes.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `VARCHAR(64)` | `PRIMARY KEY`, indexed | Deterministic user identifier (`usr_<uuid_hex>`) |
| `email` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL`, indexed | Lowercase user email address |
| `hashed_password` | `VARCHAR(255)` | `NOT NULL` | Argon2/Bcrypt hashed password string |
| `created_at` | `DATETIME(timezone=True)` | `NOT NULL`, default UTC | Timestamp of account creation |
| `updated_at` | `DATETIME(timezone=True)` | `NOT NULL`, default UTC | Timestamp of last account update |

### 2.2 `repository_metadata` Table
Tracks user-owned repositories, upload statuses, and storage snapshots.

| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `repository_id` | `VARCHAR(64)` | `PRIMARY KEY`, indexed | Unique ID: `repo_{hash(owner_id + name)}` |
| `owner_id` | `VARCHAR(64)` | `FOREIGN KEY(users.id)`, indexed | Reference to repo owner in `users` |
| `name` | `VARCHAR(255)` | `NOT NULL` | Display/directory name of repository |
| `storage_path` | `VARCHAR(512)` | `NOT NULL` | Absolute or relative filesystem root directory |
| `status` | `VARCHAR(32)` | `NOT NULL`, default `'pending'` | Lifecycle state: `'pending'`, `'analyzing'`, `'ready'`, `'failed'` |
| `snapshot_version`| `INTEGER` | `NOT NULL`, default `1` | Incrementing version counter for snapshots |
| `error_message` | `TEXT` | `NULLABLE` | Stacktrace or error description on analysis failure |
| `created_at` | `DATETIME(timezone=True)` | `NOT NULL`, default UTC | Ingestion creation timestamp |
| `updated_at` | `DATETIME(timezone=True)` | `NOT NULL`, default UTC | Timestamp of last status change or re-analysis |

---

## 3. Database Migrations (Alembic)

Database migrations are managed via **Alembic**.

### Migration Files
- `alembic/versions/ffe48db63c68_initial_schema.py`: Baseline migration establishing the `users` and `repository_metadata` tables.

### Executing Migrations

To apply pending migrations up to head:
```bash
alembic upgrade head
```

To roll back one migration:
```bash
alembic downgrade -1
```

### Alembic Configuration
- Configured in `alembic.ini` and `alembic/env.py`.
- `render_as_batch=True` is enabled in `run_migrations_offline()` and `run_migrations_online()` to guarantee compatible schema migrations on both SQLite and PostgreSQL without lock errors or unsupported alter table statements.
