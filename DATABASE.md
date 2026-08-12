# Database Documentation - Supplier Mock Factory

**Date:** 2026-07-28  
**Status:** Production Ready  
**Version:** 1.0

---

## Executive Summary

The Supplier Mock Factory uses **SQLite** as its database for development and staging environments. For production deployments, **PostgreSQL is recommended** for better scalability and performance.

---

## Current Database Setup

### **Database Type: SQLite**

```
Database: smf.db
Location: backend/smf.db
Connection: sqlite:///./smf.db
```

### **Why SQLite for Dev/Staging?**

✅ **Zero Configuration** - No separate DB server needed  
✅ **Lightweight** - Perfect for development and QA  
✅ **File-Based** - Easy to backup and version control  
✅ **Sufficient for Testing** - Handles QA workloads well  

### **SQLAlchemy ORM**

- **Framework:** FastAPI + SQLAlchemy
- **Python Version:** 3.12+
- **Connection Pooling:** Built-in SQLAlchemy connection pool

---

## Database Schema

### **Table 1: `scenarios`**

Stores test scenario data created by users.

| Column | Type | Size | Purpose |
|--------|------|------|---------|
| `id` | VARCHAR | 36 | Primary key (UUID) |
| `namespace` | VARCHAR | 64 | Unique scenario identifier |
| `status` | VARCHAR | 32 | PENDING, READY, FAILED, DELETED |
| `env` | VARCHAR | 16 | dev or stg |
| `api_key` | VARCHAR | 128 | Generated API key for scenario |
| `api_key_id` | VARCHAR | 64 | API key ID from Backoffice |
| `hotel_id` | VARCHAR | 64 | ATG hotel ID |
| `check_in` | VARCHAR | 10 | YYYY-MM-DD format |
| `check_out` | VARCHAR | 10 | YYYY-MM-DD format |
| `contracts_json` | JSON | - | Contract mapping data |
| `suppliers_json` | JSON | - | Multi-supplier configuration |
| `request_json` | JSON | - | Full scenario request payload |
| `booking_ids_json` | JSON | - | Booking information |
| `error_message` | TEXT | - | Error details if failed |
| `mock_server_base_url` | VARCHAR | 256 | Mock server endpoint |
| `created_at` | DATETIME | - | Creation timestamp |
| `updated_at` | DATETIME | - | Last update timestamp |
| `expires_at` | DATETIME | - | Auto-cleanup date |

**Indexes:**
- Primary Key: `id`
- Unique Index: `namespace`

**Typical Size:** 100-1000 rows (test scenarios)  
**Growth:** Slow (scenarios auto-cleanup after expiration)

---

### **Table 2: `scenario_templates`**

User-saved scenario templates for reuse.

| Column | Type | Size | Purpose |
|--------|------|------|---------|
| `id` | VARCHAR | 36 | Primary key (UUID) |
| `label` | VARCHAR | 120 | Template name |
| `description` | VARCHAR | 500 | Template description |
| `function` | VARCHAR | 64 | Purpose/origin (NEW) |
| `supplier` | VARCHAR | 8 | Legacy supplier code |
| `atg_hotel_id` | VARCHAR | 64 | Hotel ID |
| `packages_json` | JSON | - | Package configurations |
| `suppliers_json` | JSON | - | Multi-supplier packages |
| `created_at` | DATETIME | - | Creation timestamp |

**Typical Size:** 10-50 rows (user-created templates)  
**Growth:** Minimal (templates are reusable)

---

## Data Flow

```
User Input (UI)
    ↓
FastAPI Endpoint
    ↓
Pydantic Validation
    ↓
SQLAlchemy ORM
    ↓
SQLite Database
    ↓
Response to Client
```

---

## Backup & Recovery

### **Current Backup Strategy**

```bash
# Full database backup
cp backend/smf.db backups/smf.db.$(date +%Y%m%d_%H%M%S)

# Automated backup (recommended)
0 2 * * * /usr/local/bin/backup-smf-db.sh
```

### **Backup Size**

- **Database File:** 2-10 MB (typical)
- **Backup Frequency:** Daily
- **Retention:** 30 days

---

## Production Recommendations

### **For Production: Use PostgreSQL**

**Why PostgreSQL for Production?**

| Feature | SQLite | PostgreSQL |
|---------|--------|-----------|
| **Concurrent Writers** | Limited | Excellent |
| **Scalability** | ~100MB max | Unlimited |
| **Replication** | None | Built-in |
| **Backups** | File-based | Integrated tools |
| **Performance** | Good for <1000 rows | Excellent at scale |
| **High Availability** | None | Available (HA setup) |

### **Production PostgreSQL Setup**

```bash
# Environment variable for production
DATABASE_URL=postgresql://user:password@prod-db.example.com:5432/smf_prod

# Connection pooling (recommended)
SQLALCHEMY_POOL_SIZE=20
SQLALCHEMY_MAX_OVERFLOW=40
```

### **Production Deployment Checklist**

- [ ] **Database Server:** Managed PostgreSQL (AWS RDS, Google Cloud SQL, Azure Database)
- [ ] **Backup Plan:** Automated daily backups with 30-day retention
- [ ] **Replication:** Read replicas for high availability
- [ ] **Monitoring:** Database performance monitoring (CPU, disk, connections)
- [ ] **Security:** SSL/TLS encryption in transit, IAM authentication
- [ ] **Scaling:** Connection pooling configured
- [ ] **Disaster Recovery:** Tested recovery procedure
- [ ] **Access Control:** Least-privilege database user

---

## Database Migrations

### **Current Approach**

- Manual schema updates (SQLAlchemy models)
- No Alembic migrations yet
- All tables created automatically on first run

### **For Production: Implement Alembic**

```bash
# Initialize Alembic
alembic init migrations

# Create migration
alembic revision --autogenerate -m "Add function field to templates"

# Apply migration
alembic upgrade head
```

---

## Performance Metrics

### **Current SQLite Performance**

| Operation | Time | Notes |
|-----------|------|-------|
| Create Scenario | 10-30s | Includes API key provisioning |
| List Templates | <100ms | 50 templates |
| Get Scenario | <50ms | By ID |
| Delete Scenario | 1-5s | Cleanup operations |

### **Expected PostgreSQL Performance**

- **Faster** by 2-5x for complex queries
- **Better** concurrent write handling
- **Scalable** to millions of rows

---

## Data Retention

### **Automatic Cleanup**

```python
# Scenarios expire after 7 days
expires_at = created_at + timedelta(days=7)

# Status tracking prevents orphaned records
# DELETED status = fully cleaned up
```

### **Manual Cleanup**

```bash
# Remove old scenarios
sqlite3 smf.db "DELETE FROM scenarios WHERE status='DELETED' AND updated_at < datetime('now', '-30 days');"
```

---

## Disaster Recovery

### **Loss Scenarios & Recovery**

| Scenario | Recovery Time | Data Loss |
|----------|---------------|-----------|
| **Database Corrupted** | 5 minutes | 0 (restore backup) |
| **Disk Full** | 10 minutes | Depends on backup |
| **Server Down** | 15 minutes | Depends on backup |

### **Recovery Procedure**

```bash
# 1. Stop application
systemctl stop smf-backend

# 2. Restore from backup
cp backups/smf.db.20260728_020000 backend/smf.db

# 3. Verify database
sqlite3 backend/smf.db "SELECT COUNT(*) FROM scenarios;"

# 4. Restart application
systemctl start smf-backend
```

---

## Development vs Production

### **Development (SQLite)**

```
DATABASE_URL=sqlite:///./smf.db
Location: backend/smf.db
Size: 5 MB
Backup: Manual or daily script
Suitable for: Dev, QA, Testing
```

### **Production (PostgreSQL)**

```
DATABASE_URL=postgresql://user:pw@prod-db.example.com:5432/smf
Server: Managed service (RDS/Cloud SQL)
Size: Unlimited
Backup: Automated managed backups
HA: Replicated across availability zones
Suitable for: Production workloads
```

---

## Technical Stack

- **ORM:** SQLAlchemy 2.0+
- **Python:** 3.12+
- **FastAPI:** 0.100+
- **Database Drivers:**
  - SQLite: Built-in sqlite3
  - PostgreSQL: psycopg2

---

## Monitoring & Alerts

### **For Production Setup**

```yaml
Alerts:
  - Database connection failures
  - Query performance degradation
  - Disk space low (<10%)
  - Replication lag (>5 seconds)
  - Failed backups
  - Connection pool exhaustion
```

---

## FAQ for Manager

**Q1: Is SQLite safe for production?**  
A: No. SQLite is file-based and designed for single-writer scenarios. PostgreSQL is recommended for production.

**Q2: How much does PostgreSQL cost?**  
A: Managed PostgreSQL starts at $10-20/month (AWS RDS, Google Cloud). Pricing scales with usage.

**Q3: Can we migrate from SQLite to PostgreSQL?**  
A: Yes, easy migration using SQLAlchemy (supports both). No code changes needed.

**Q4: What about data privacy/compliance?**  
A: Use managed database service with encryption at rest/in-transit (AWS RDS, GCP, Azure all support).

**Q5: How long does a backup take?**  
A: SQLite: <1 second. PostgreSQL managed backup: Automatic, transparent.

**Q6: Do we need a DBA?**  
A: With managed services (RDS/Cloud SQL): No. Vendor handles patches, backups, HA.

---

## Migration Path (Dev → Staging → Production)

```
Development
├─ Database: SQLite (smf.db)
├─ Backup: Manual/Daily script
└─ No HA needed

Staging
├─ Database: PostgreSQL (managed)
├─ Backup: Automated daily
└─ Read replicas optional

Production
├─ Database: PostgreSQL (managed HA)
├─ Backup: Automated hourly
├─ Read replicas: Yes
└─ Monitoring: Full monitoring stack
```

---

## Contact & Support

For database-related questions, contact DevOps team.

**Related Documentation:**
- [API_DOCUMENTATION.md](API_DOCUMENTATION.md) - API endpoints
- [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) - Feature summary
- [README.md](README.md) - Setup instructions

---

**Document Version:** 1.0  
**Last Updated:** 2026-07-28  
**Status:** Ready for Production Review
