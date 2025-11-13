# ChromaDB Installation Log - Persistent Storage

**Date**: 2025-10-10  
**Location**: `/mcp_rag_eib/etc/chromadb`  
**Port**: 8080  
**Status**: ✅ Successfully Installed and Running

## Installation Steps Taken

### 1. Directory Structure Created
```bash
/mcp_rag_eib/
├── etc/
│   └── chromadb/
│       └── venv/          # Python virtual environment
└── data/
    └── chromadb/          # Persistent data storage
```

### 2. Python Virtual Environment
- **Python Version**: 3.11.12
- **Location**: `/mcp_rag_eib/etc/chromadb/venv`
- **Pip Version**: 25.2

### 3. Packages Installed
```
chromadb==0.4.15
fastapi==0.95.2
uvicorn==0.22.0
pydantic==1.10.9
typing-extensions==4.7.1
```

**Dependencies** (auto-installed):
- numpy 2.3.3
- grpcio 1.74.0
- onnxruntime 1.23.1
- kubernetes 34.1.0
- huggingface-hub 0.35.3
- tokenizers 0.22.1
- And many more supporting packages

### 4. Systemd Service Configuration

**Service Name**: `chromadb-persistent.service`  
**Service File**: `/etc/systemd/system/chromadb-persistent.service`

**Configuration**:
- User: Terry.McGuinness
- Working Directory: `/mcp_rag_eib/data/chromadb`
- Port: 8080
- Host: 0.0.0.0 (accessible from network)
- Persist Directory: `/mcp_rag_eib/data/chromadb`
- Auto-restart: Enabled (5 second delay)

**Environment Variables**:
```bash
TELEMETRY_DISABLED=1
OTEL_PYTHON_DISABLED=1
OTEL_SDK_DISABLED=1
CHROMA_SERVER_HTTP_PORT=8080
CHROMA_SERVER_HOST=0.0.0.0
PERSIST_DIRECTORY=/mcp_rag_eib/data/chromadb
ALLOW_RESET=true
```

### 5. Service Status
```
✅ Service enabled (starts on boot)
✅ Service active and running
✅ API endpoint responding on port 8080
✅ Heartbeat: http://127.0.0.1:8080/api/v1/heartbeat
```

## Testing and Verification

### Heartbeat Test
```bash
curl -s http://127.0.0.1:8080/api/v1/heartbeat
# Response: {"nanosecond heartbeat": 1760111758499688297}
```

### Collections Check
```bash
curl -s http://127.0.0.1:8080/api/v1/collections
# Response: [] (empty, as expected on fresh install)
```

### Service Management Commands
```bash
# Check status
sudo systemctl status chromadb-persistent.service

# View logs
sudo journalctl -u chromadb-persistent.service -f

# Restart
sudo systemctl restart chromadb-persistent.service

# Stop
sudo systemctl stop chromadb-persistent.service

# Start
sudo systemctl start chromadb-persistent.service
```

## Key Lessons Learned

### ✅ What Worked
1. **Direct installation to persistent storage** - No copying between `/etc` and `/contrib`
2. **Python 3.11 module** - Using system Python 3.11 from `/apps/modules`
3. **Virtual environment in persistent storage** - Survives reboots
4. **Port 8080** - Clean port without conflicts
5. **Systemd service** - Reliable auto-start and management

### 📝 Important Notes
1. **Storage location**: All ChromaDB files are on the 25GB persistent drive
2. **Data persistence**: Database files will be created in `/mcp_rag_eib/data/chromadb/`
3. **Network accessible**: Configured to bind to 0.0.0.0 (all interfaces)
4. **No root installation**: Runs as user `Terry.McGuinness`
5. **Telemetry disabled**: No external tracking or reporting

### 🎯 Next Steps
1. Set up MCP server Node.js environment in `/mcp_rag_eib/mcp_server_node`
2. Clone Git repository to `/mcp_rag_eib/mcp_server_node/global-workflow_MCP_node.js-RAG`
3. Configure MCP servers to use ChromaDB at `http://localhost:8080`
4. Populate ChromaDB with Global Workflow documentation
5. Test RAG functionality with MCP tools

## Architecture Benefits

### Persistent Storage Strategy
- **Single mount point**: Everything on `/mcp_rag_eib`
- **Clear separation**: 
  - `/etc/chromadb` = software installation
  - `/data/chromadb` = runtime data
- **Backup simplicity**: Just backup `/mcp_rag_eib`
- **VM restart proof**: All data survives reboots

### Resource Usage
- **Memory**: ~56MB
- **CPU**: Minimal (871ms startup)
- **Disk**: Will grow with collections
- **Storage Available**: 23GB free on `/mcp_rag_eib`

## Troubleshooting

### If service fails to start
```bash
# Check logs
sudo journalctl -u chromadb-persistent.service -n 50

# Check permissions
ls -la /mcp_rag_eib/data/chromadb
# Should be owned by Terry.McGuinness:Terry.McGuinness

# Test venv manually
cd /mcp_rag_eib/etc/chromadb
source venv/bin/activate
python -c "import chromadb; print(chromadb.__version__)"
```

### If port 8080 is in use
```bash
# Check what's using the port
sudo lsof -i :8080
sudo netstat -tulpn | grep 8080
```

### If collections don't persist
```bash
# Verify data directory exists and has correct permissions
ls -la /mcp_rag_eib/data/chromadb/
# Check service is using correct PERSIST_DIRECTORY
sudo systemctl cat chromadb-persistent.service | grep PERSIST_DIRECTORY
```

---
**Installation Complete**: 2025-10-10 15:55:42 UTC  
**Verified By**: Sonnet 4.5 Preview AI Assistant  
**Status**: Production Ready ✅
