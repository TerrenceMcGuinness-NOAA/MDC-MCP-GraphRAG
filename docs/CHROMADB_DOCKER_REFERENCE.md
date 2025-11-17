# ChromaDB Docker Setup - Quick Reference

## Overview
ChromaDB runs as a Docker container managed by systemd. This approach eliminates Python dependency conflicts and SQLite version issues.

## Architecture
```
Host System (Rocky 9)
├── Systemd Service: chromadb-docker.service
└── Docker Container: chromadb/chroma:latest
    ├── Port: 8000 (container) -> 8080 (host)
    ├── Volume: /mcp_rag_eib/data/chromadb -> /chroma/chroma
    └── API: v2 (http://localhost:8080/api/v2)
```

## Service Management

### Status
```bash
sudo systemctl status chromadb-docker.service
```

### Start/Stop/Restart
```bash
sudo systemctl start chromadb-docker.service
sudo systemctl stop chromadb-docker.service
sudo systemctl restart chromadb-docker.service
```

### Logs
```bash
# Systemd logs
sudo journalctl -u chromadb-docker.service -n 50 --no-pager

# Container logs
sudo docker logs chromadb

# Follow logs
sudo docker logs -f chromadb
```

### Enable/Disable at Boot
```bash
sudo systemctl enable chromadb-docker.service   # Start at boot
sudo systemctl disable chromadb-docker.service  # Don't start at boot
```

## Docker Container Management

### View Running Container
```bash
sudo docker ps | grep chromadb
```

### Access Container Shell
```bash
sudo docker exec -it chromadb /bin/bash
```

### View Container Filesystem
```bash
# List data directory
sudo docker exec chromadb ls -la /chroma/chroma/

# Check ChromaDB version
sudo docker exec chromadb python -c "import chromadb; print(chromadb.__version__)"
```

### Manual Container Start (without systemd)
```bash
sudo docker run --name chromadb \
    --rm \
    -p 8080:8000 \
    -v /mcp_rag_eib/data/chromadb:/chroma/chroma \
    -e IS_PERSISTENT=TRUE \
    -e PERSIST_DIRECTORY=/chroma/chroma \
    -e ANONYMIZED_TELEMETRY=FALSE \
    chromadb/chroma:latest
```

## API Testing

### Health Check (v2 API)
```bash
curl http://127.0.0.1:8080/api/v2/heartbeat
# Expected: {"nanosecond heartbeat":1763395944218374329}
```

### List Collections
```bash
curl http://127.0.0.1:8080/api/v2/collections
```

### Version Info
```bash
curl http://127.0.0.1:8080/api/v2/version
```

## Troubleshooting

### Container Won't Start
```bash
# Check if port 8080 is in use
sudo lsof -i :8080

# Check Docker service
sudo systemctl status docker

# Check for existing container
sudo docker ps -a | grep chromadb
sudo docker rm chromadb  # Remove if stuck

# Check image exists
sudo docker images | grep chromadb
```

### Data Not Persisting
```bash
# Verify volume mount
sudo docker inspect chromadb | grep -A 10 Mounts

# Check host directory permissions
ls -la /mcp_rag_eib/data/chromadb/

# Verify data inside container
sudo docker exec chromadb ls -la /chroma/chroma/
```

### Permission Issues
```bash
# Fix ownership of data directory
sudo chown -R Terry.McGuinness:Terry.McGuinness /mcp_rag_eib/data/chromadb
```

### Service Fails to Start
```bash
# Check detailed status
sudo systemctl status chromadb-docker.service -l

# Check journalctl logs
sudo journalctl -u chromadb-docker.service -n 100

# Verify service file
cat /etc/systemd/system/chromadb-docker.service

# Reload systemd after changes
sudo systemctl daemon-reload
```

## Upgrading ChromaDB

### Pull Latest Image
```bash
# Pull new image
sudo docker pull chromadb/chroma:latest

# Restart service (will use new image)
sudo systemctl restart chromadb-docker.service
```

### Use Specific Version
```bash
# Pull specific version
sudo docker pull chromadb/chroma:0.5.0

# Update service file to use version tag
sudo vim /etc/systemd/system/chromadb-docker.service
# Change: chromadb/chroma:latest -> chromadb/chroma:0.5.0

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart chromadb-docker.service
```

## Data Backup

### Backup ChromaDB Data
```bash
# Stop service
sudo systemctl stop chromadb-docker.service

# Backup data directory
sudo tar -czf chromadb-backup-$(date +%Y%m%d).tar.gz /mcp_rag_eib/data/chromadb/

# Restart service
sudo systemctl start chromadb-docker.service
```

### Restore ChromaDB Data
```bash
# Stop service
sudo systemctl stop chromadb-docker.service

# Restore backup
sudo tar -xzf chromadb-backup-20251117.tar.gz -C /

# Fix permissions
sudo chown -R Terry.McGuinness:Terry.McGuinness /mcp_rag_eib/data/chromadb

# Restart service
sudo systemctl start chromadb-docker.service
```

## Performance Monitoring

### Check Resource Usage
```bash
# Container stats
sudo docker stats chromadb

# Memory usage
sudo docker exec chromadb free -h

# Disk usage
sudo du -sh /mcp_rag_eib/data/chromadb/
```

### Check Collection Statistics
```python
import chromadb
client = chromadb.HttpClient(host="localhost", port=8080)
collections = client.list_collections()
for c in collections:
    print(f"{c.name}: {c.count()} documents")
```

## Migration Notes

### From Spack/pip Installation
- Old service: `chromadb-spack.service` (disabled)
- Old installation: Spack Python + pip user packages (no longer needed)
- Data location: **unchanged** - /mcp_rag_eib/data/chromadb
- Existing collections: **preserved** - accessible via volume mount

### Why Docker?
1. ✅ No Python version conflicts (self-contained)
2. ✅ No SQLite version issues (container has correct version)
3. ✅ No venv/site-packages confusion (isolated environment)
4. ✅ Easy upgrades (docker pull)
5. ✅ Clean separation from development environment
6. ✅ Faster startup (30s vs 90s)

## Service File Location
- **Active**: `/etc/systemd/system/chromadb-docker.service`
- **Reference**: `/mcp_rag_eib/eib-mcp-rag-server/SETUP/chromadb-docker.service`

## Provision Script Integration
ChromaDB Docker setup is integrated in:
- `SETUP/provision_mcp_rag_persistent.sh` (v3.5.0+)
- STEP 7: Pull Docker image
- STEP 8: Create and start systemd service
