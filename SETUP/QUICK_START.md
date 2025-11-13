# Quick Start Guide - MCP RAG Infrastructure v3.0

## 🚀 Start Here (3 Commands)

```bash
# 1. Navigate to setup directory
cd /mcp_rag_eib/SETUP

# 2. Run provisioning with fresh start (RECOMMENDED for first time)
sudo ./provision_mcp_rag_persistent.sh --fresh

# 3. After completion, source environment
source /mcp_rag_eib/mcp_server_node/mcp-env.sh
```

**Expected Duration**: 15-20 minutes

---

## ✅ Quick Verification (3 Commands)

```bash
# 1. Check ChromaDB is running
curl http://127.0.0.1:8080/api/v1/heartbeat

# 2. Check venv size (should be ~300MB, not 7GB)
du -sh /mcp_rag_eib/etc/chromadb/venv

# 3. Check free space (should be ~19GB free)
df -h /mcp_rag_eib
```

---

## 📊 What Gets Installed

| Component | Location | Size | Purpose |
|-----------|----------|------|---------|
| ChromaDB | `/mcp_rag_eib/etc/chromadb` | ~300MB | Vector database server |
| MCP Server | `/mcp_rag_eib/mcp_server_node` | ~400MB | MCP tools & RAG system |
| Git Repo | `/mcp_rag_eib/global-workflow...` | 4.8GB | Source code (persistent) |
| Node.js | System-wide | ~100MB | Runtime for MCP server |
| Python 3.11 | Module system | ~50MB | Runtime for ChromaDB |
| Docker | System-wide | ~200MB | Container platform |

**Total**: ~5-6GB (leaves 19-20GB free)

---

## 🔄 Run Modes

### Normal Mode (Default)
```bash
sudo ./provision_mcp_rag_persistent.sh
```
- Preserves caches (npm, pip, transformers)
- Faster subsequent runs
- Rebuilds installations only

### Fresh Start Mode
```bash
sudo ./provision_mcp_rag_persistent.sh --fresh
```
- Clears ALL caches
- Removes old installations
- Complete clean slate
- **RECOMMENDED for first run**

---

## 🎯 What's New in v3.0

✅ No `/contrib` dependencies (fully persistent)  
✅ Lightweight ChromaDB venv (300MB vs 7.1GB)  
✅ Module system integration (Python 3.11)  
✅ Fresh start option (`--fresh` flag)  
✅ Better error handling (timeouts, fallbacks)  
✅ Git repo at persistent root (easier updates)

---

## 🐛 Troubleshooting

### Script hangs on DNF operations
**Fix**: Wait for timeout (5-10 min) or press Ctrl-C and re-run

### ChromaDB won't start
```bash
# Check logs
journalctl -u chromadb-persistent.service -n 50

# Restart service
sudo systemctl restart chromadb-persistent.service
```

### "Python 3.11 not found"
```bash
# Check module system
module avail python

# Load module
module load python/3.11

# Verify
python3.11 --version
```

### "Node.js not found"
```bash
# Check if installed
which node

# Reset and reinstall
sudo dnf module reset nodejs -y
sudo dnf module install nodejs:20 -y
```

### Disk space issues
```bash
# Check usage
df -h /mcp_rag_eib

# Run with --fresh to clear old data
sudo ./provision_mcp_rag_persistent.sh --fresh
```

---

## 📝 After Installation

### 1. Source Environment (Required)
```bash
source /mcp_rag_eib/mcp_server_node/mcp-env.sh
```

### 2. Verify Services
```bash
systemctl status chromadb-persistent.service
systemctl status docker.service
```

### 3. Test ChromaDB
```bash
curl http://127.0.0.1:8080/api/v1/heartbeat
curl http://127.0.0.1:8080/api/v1/collections
```

### 4. Test MCP Server
```bash
cd /mcp_rag_eib/mcp_server_node
node src/UnifiedMCPServer.js core
```

### 5. Check Logs
```bash
# ChromaDB logs
journalctl -u chromadb-persistent.service -f

# MCP server logs (when started)
tail -f /mcp_rag_eib/mcp_server_node/logs/*.log
```

---

## 🔍 Quick Status Check

```bash
# One-liner to check everything
echo "ChromaDB: $(systemctl is-active chromadb-persistent.service)"; \
echo "Docker: $(systemctl is-active docker)"; \
echo "Venv size: $(du -sh /mcp_rag_eib/etc/chromadb/venv 2>/dev/null | cut -f1)"; \
echo "Free space: $(df -h /mcp_rag_eib | tail -1 | awk '{print $4}')"; \
echo "Node: $(node --version 2>/dev/null || echo 'not found')"; \
echo "Python: $(python3.11 --version 2>&1 | head -1 || echo 'not found')"
```

---

## 📚 Documentation

- **Full Changelog**: `PROVISIONING_SCRIPT_V3_CHANGELOG.md`
- **Readiness Report**: `PROVISIONING_READINESS_REPORT.md`
- **Provisioning Script**: `provision_mcp_rag_persistent.sh`
- **Environment Config**: `/mcp_rag_eib/mcp_server_node/mcp-env.sh`

---

## ⚡ Emergency Reset

If everything breaks:
```bash
# Stop services
sudo systemctl stop chromadb-persistent.service
sudo systemctl stop mcp-server-persistent.service

# Nuclear option - clear everything
sudo rm -rf /mcp_rag_eib/etc/chromadb
sudo rm -rf /mcp_rag_eib/mcp_server_node/node_modules
sudo rm -rf /mcp_rag_eib/cache/*
sudo rm -rf /mcp_rag_eib/data/chromadb/*

# Start fresh
cd /mcp_rag_eib/SETUP
sudo ./provision_mcp_rag_persistent.sh --fresh
```

---

**Version**: 3.0.0  
**Last Updated**: 2025-10-14  
**Status**: ✅ Production Ready
