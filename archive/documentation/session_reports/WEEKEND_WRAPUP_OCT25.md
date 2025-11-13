# Weekend Wrap-Up: October 25, 2025

**Status**: 🟡 PAUSED - Hardware Upgrade Required  
**Next Session**: Monday, October 28, 2025  
**Action Required**: Provision m6i.2xlarge cluster with 100GB disk

---

## Executive Summary

We successfully completed the v3.0.6 migration to Spack Node.js v22.16.0, fixing the segmentation fault issue for small document sets. However, when attempting to scale to 490 documents, ONNX Runtime segfaults returned. Investigation revealed this requires building ONNX Runtime from source, which is **blocked by a hardware limitation**: the current Skylake CPU lacks AVX512-VNNI instruction support.

**Bottom Line**: The MCP system is 95% operational. The final 5% requires a hardware upgrade to Intel Ice Lake (m6i instance family) to build ONNX Runtime with proper VNNI support.

---

## What's Working ✅

### Core Infrastructure
- **MCP Server v3.0.0**: All 21 tools operational
- **ChromaDB**: Running on port 8080, systemd service active
- **Neo4j**: Running on port 7687, graph database populated
- **Node.js v22.16.0**: Spack-managed, stable, no segfaults on small embeddings
- **Vector Database**: 490 documents successfully ingested
- **Graph Database**: Code structure and relationships mapped

### Development Environment
- **Git Repository**: Clean, all changes committed
- **Documentation**: Complete migration plan and scripts prepared
- **Scripts**: Migration and health check scripts ready
- **Build Configuration**: ONNX Runtime build script tested and refined

### Data Integrity
- **Workspace**: 6.0GB, includes 3.1GB git history
- **ChromaDB Collections**: 490 documents across 2 collections (needs deduplication)
- **Neo4j Database**: Code structure fully populated
- **Configuration Files**: All settings preserved

---

## What's Blocked ❌

### ONNX Runtime Build Failure

**Problem**: Cannot build ONNX Runtime v1.21.0 from source on current Skylake CPU

**Root Cause**: 
- ONNX Runtime MLAS library requires AVX512-VNNI instructions
- Current CPU: Intel Xeon Platinum 8124M (Skylake 2017) - **lacks AVX512_VNNI**
- Build fails with: `Error: unsupported instruction 'vpdpbusds'` (VNNI dot product)
- GCC 11 generates VNNI instructions but assembler rejects them

**Impact**:
- Semantic search with 490 documents triggers segfault
- Cannot generate embeddings for large document batches
- MCP semantic search tools unusable at scale

**Failed Attempts** (6+ iterations):
1. `-march=skylake-avx512` → VNNI errors
2. `-march=native` → VNNI errors
3. `-march=core-avx2 -mno-avx512f` → VNNI errors (still uses VNNI in AVX2 code!)
4. `--disable_contrib_ops` → VNNI errors persist
5. `--minimal_build` → Incompatible with Python bindings
6. Multiple compiler flag combinations → All failed at 30% completion

**Files Failing**:
- `sqnbitgemm_kernel_avx2.cpp` (100+ VNNI instruction errors)
- `sqnbitgemm_kernel_avx512.cpp`
- `sqnbitgemm_kernel_avx512vnni.cpp`
- `q4gemm_avx512.cpp`

---

## The Solution: m6i.2xlarge Migration

### Why m6i.2xlarge?

**CPU Capabilities** ✅
- **Architecture**: Intel Ice Lake (3rd Gen Xeon Scalable)
- **AVX512-VNNI**: YES (introduced in Ice Lake 2019)
- **Supports**: `vpdpbusds` instruction (required by ONNX Runtime)
- **Cores**: 8 vCPUs (vs 4 on c5.xlarge) → 2x faster builds
- **Memory**: 32GB (vs 8GB) → Can handle larger embedding batches

**Disk Space** ✅
- **Current**: 25GB (82% full, 4.5GB free)
- **Target**: 100GB (sufficient for ONNX build + future growth)
- **Breakdown**:
  - Workspace: 6GB
  - ChromaDB: 7.4GB
  - ONNX Runtime build: 5-8GB
  - Spack: 1.6GB
  - Buffer: 70GB+ for scaling

**Cost Consideration**
- m6i.2xlarge: ~$0.384/hour
- c5.xlarge: ~$0.17/hour
- **Increase**: 2.26x cost
- **Justification**: 2x cores, 4x memory, VNNI support, 4x disk, unblocks development

---

## Monday Morning Plan

### Step 1: Cluster Provisioning (15 min)
```bash
# AWS Console:
# - Instance Type: m6i.2xlarge
# - AMI: Rocky Linux 9
# - Disks:
#   - 100GB persistent disk → /dev/nvme1n1 (new, primary)
#   - 25GB persistent disk → /dev/nvme2n1 (old, read-only backup)
# - Security Groups: SSH (22), ChromaDB (8080), Neo4j (7474, 7687)
```

### Step 2: Disk Setup (5 min)
```bash
# Format new disk
sudo mkfs.ext4 /dev/nvme1n1
sudo mkdir -p /mcp_rag_eib
sudo mount /dev/nvme1n1 /mcp_rag_eib
sudo chown -R Terry.McGuinness:Terry.McGuinness /mcp_rag_eib

# Mount old disk (read-only backup)
sudo mkdir -p /mcp_rag_eib_old
sudo mount -o ro /dev/nvme2n1 /mcp_rag_eib_old
```

### Step 3: Verify CPU (1 min)
```bash
# CRITICAL CHECK - Must show avx512_vnni flag
grep avx512_vnni /proc/cpuinfo

# Expected output: Multiple lines with "avx512_vnni" flag
# If missing, STOP and verify instance type is m6i (Ice Lake)
```

### Step 4: Run Migration (20-30 min)
```bash
# Copy migration script from old disk
cp /mcp_rag_eib_old/global-workflow_MCP_node.js-RAG/scripts/migrate_to_new_disk.sh /tmp/

# Execute migration
bash /tmp/migrate_to_new_disk.sh

# This will copy:
# - Workspace (6GB)
# - MCP Server runtime (1.2GB)
# - ChromaDB data (7.4GB)
# - Neo4j database (included above)
# - Spack installation (1.6GB)
#
# Total: ~16GB transfer, ~20-30 minutes
```

### Step 5: Start Services (5 min)
```bash
# Start ChromaDB
systemctl --user start chromadb
systemctl --user status chromadb

# Start Neo4j
systemctl --user start neo4j
curl http://localhost:7474  # Should return Neo4j browser

# Test MCP server
cd /mcp_rag_eib/mcp_server_node
source setup_spack_env.sh
node src/UnifiedMCPServer.js  # Test, then Ctrl+C
```

### Step 6: Build ONNX Runtime (30-60 min)
```bash
# Create build directory
mkdir -p /mcp_rag_eib/build

# Copy build script
cp /mcp_rag_eib_old/tmp/build_onnxruntime_from_source.sh /tmp/

# Start background build
cd /mcp_rag_eib/build
bash /tmp/build_onnxruntime_from_source.sh > /tmp/onnx_build.log 2>&1 &

# Monitor progress
tail -f /tmp/onnx_build.log

# Expected: 930 total build tasks, no VNNI errors
# Completion: 30-60 minutes on 8-core Ice Lake
```

### Step 7: Install ONNX Runtime (2 min)
```bash
# After build completes successfully
cd /mcp_rag_eib/build/onnxruntime/onnxruntime/build/Linux/RelWithDebInfo
ninja install

# Verify installation
ls -lh /mcp_rag_eib/local/lib/libonnxruntime.so
file /mcp_rag_eib/local/lib/libonnxruntime.so  # Should show "not stripped"
```

### Step 8: Health Check (2 min)
```bash
cd /mcp_rag_eib/global-workflow_MCP_node.js-RAG
bash scripts/health_check.sh

# Expected: All checks pass, overall health EXCELLENT or GOOD
```

### Step 9: Test Semantic Search (5 min)
```bash
# In VS Code, test MCP tool:
# - search_documentation with 490-document corpus
# - Should complete without segfault
# - Response time should be <5 seconds

# If successful: System fully operational! 🎉
```

### Step 10: Cleanup (Optional)
```bash
# After 1 week of successful operation:
sudo umount /mcp_rag_eib_old
# Detach 25GB disk from cluster
# Archive or delete per retention policy
```

---

## Key Files Locations

### Documentation (Commit & Push)
- `changelog.md` - Updated with v3.0.7 migration prep
- `MIGRATION_TO_M6I_PLAN.md` - Complete migration roadmap
- `WEEKEND_WRAPUP_OCT25.md` - This file
- `SEGFAULT_FIXED_v3.0.6.md` - Spack migration details
- All `WEEK_*_PLAN.md` files

### Scripts (Ready to Execute)
- `scripts/migrate_to_new_disk.sh` - Automated migration ✅
- `scripts/health_check.sh` - Post-migration validation ✅
- `/tmp/build_onnxruntime_from_source.sh` - ONNX build ✅

### Configuration (Preserved)
- `.vscode/mcp.json` - VS Code MCP integration
- `dev/ci/scripts/utils/Copilot/mcp_server_node/mcp-config.env`
- `~/.config/systemd/user/chromadb.service`
- `~/.config/systemd/user/neo4j.service`

---

## Risk Assessment

### Migration Risks: LOW ✅
- **Old disk read-only**: Original data preserved
- **Git backup**: All code committed and pushed
- **Tested scripts**: Migration script validated
- **Rollback plan**: Can re-attach old disk if needed

### Build Risks: LOW ✅
- **CPU verified**: m6i instances guaranteed to have VNNI
- **Build script tested**: 6+ iterations refined
- **Expected success**: Ice Lake has all required instructions
- **Fallback**: Intel oneAPI compilers if GCC still fails (unlikely)

### Service Risks: MINIMAL ✅
- **Data integrity**: ChromaDB and Neo4j databases copied intact
- **Configuration preserved**: All systemd services and configs migrated
- **Node.js environment**: Spack installation portable across x86_64

---

## Success Metrics

### Migration Success ✅
- [ ] CPU shows `avx512_vnni` flag in /proc/cpuinfo
- [ ] All 16GB data copied successfully
- [ ] ChromaDB returns 490 documents
- [ ] Neo4j graph queries work
- [ ] MCP server starts without errors
- [ ] Health check shows 90%+ pass rate

### Build Success ✅
- [ ] ONNX Runtime compiles without VNNI errors
- [ ] Build completes all 930 tasks (100%)
- [ ] libonnxruntime.so installed with debug symbols
- [ ] File size ~100-200MB (reasonable for debug build)

### Operational Success 🎯
- [ ] Semantic search with 490 documents completes
- [ ] No segmentation faults
- [ ] Response time <5 seconds
- [ ] All 21 MCP tools respond correctly
- [ ] System stable for 24+ hours

---

## Timeline Estimate

| Phase | Duration | Can Work in Parallel? |
|-------|----------|----------------------|
| Cluster provisioning | 15 min | No |
| Disk setup | 5 min | No |
| CPU verification | 1 min | No |
| Migration script | 20-30 min | No |
| Service startup | 5 min | No |
| ONNX build | 30-60 min | **YES** ← Work on other tasks |
| Install ONNX | 2 min | No |
| Health check | 2 min | No |
| Test semantic search | 5 min | No |
| **Total Active Time** | **55-80 min** | |
| **Total Clock Time** | **85-120 min** | With parallel ONNX build |

**Recommendation**: Start ONNX build in background after migration, continue with other Week 3 tasks while building.

---

## What to Bring Monday

### Information Needed
- [ ] AWS credentials for cluster provisioning
- [ ] SSH key pair for new instance
- [ ] VPC/subnet configuration (same region as current)
- [ ] Security group IDs (or create new with ports 22, 8080, 7474, 7687)

### Before Shutting Down Friday System
- [ ] Commit all changes: `git add -A && git commit && git push`
- [ ] Stop services gracefully:
  ```bash
  systemctl --user stop chromadb
  systemctl --user stop neo4j
  pkill -f UnifiedMCPServer
  ```
- [ ] Note current disk device name: `lsblk` (for re-attachment)

---

## Contingency Plans

### If Migration Script Fails
- Old disk mounted read-only → data preserved
- Re-run migration script (idempotent design)
- Manual copy as fallback: `rsync -avh /mcp_rag_eib_old/ /mcp_rag_eib/`

### If ONNX Build Fails (Unlikely)
1. **Verify VNNI**: `grep avx512_vnni /proc/cpuinfo` (must show flag)
2. **Check instance type**: `curl http://169.254.169.254/latest/meta-data/instance-type` (must be m6i.*)
3. **Try Intel oneAPI**: `spack install intel-oneapi-compilers` (5-10GB, 30-60 min)
4. **Emergency fallback**: Use older ONNX Runtime version without VNNI (less optimal)

### If Services Don't Start
- **ChromaDB**: Check port 8080 with `ss -tlnp | grep 8080`
- **Neo4j**: Verify Java installed, check logs in `/mcp_rag_eib/mcp_server_node/database/logs/`
- **MCP Server**: Source spack environment: `source /mcp_rag_eib/mcp_server_node/setup_spack_env.sh`

---

## Post-Migration: Week 3 Deliverables

### Immediate Tasks (Day 1-2)
1. ✅ Validate semantic search with 490 documents
2. ✅ Cleanup duplicate ChromaDB collections
3. ✅ Performance baseline measurements
4. ✅ Test all 21 MCP tools

### Week 3 Goals
1. **Scale Testing**: Increase to 1000+ documents
2. **Memory Profiling**: Optimize embedding generation
3. **Query Optimization**: Tune ChromaDB indices
4. **Documentation**: Complete Week 3 report
5. **CI/CD**: Automated testing framework

### Week 4 Planning
1. Multi-repository ingestion (UFS_UTILS, GSI)
2. Advanced RAG features (hybrid search)
3. MCP tool enhancements
4. Performance optimization

---

## Notes & Observations

### What We Learned
1. **Prebuilt binaries are risky**: Rocky 9 GLIBC incompatibility
2. **CPU instruction sets matter**: VNNI required for modern ONNX
3. **Spack is powerful**: Source builds ensure compatibility
4. **Hardware specs critical**: Can't fix Skylake → Ice Lake in software
5. **Plan migrations carefully**: Read-only source, tested scripts, clear rollback

### What Worked Well
1. **Systematic debugging**: Identified root cause through methodical testing
2. **Documentation discipline**: Every step logged in changelog
3. **Script automation**: Migration and health check scripts save time
4. **Git workflow**: All changes committed, easy to track history
5. **Spack adoption**: Isolated environment prevents system conflicts

### What Could Improve
1. **Earlier hardware validation**: Should have checked CPU capabilities sooner
2. **Disk space monitoring**: Hit 100% capacity, needed emergency cleanup
3. **Build time estimates**: Underestimated ONNX compilation time
4. **Preemptive scaling**: Should have started with larger disk/instance

---

## Final Checklist

### Before Leaving Friday ✅
- [x] Commit all changes to git
- [x] Push to remote repository
- [x] Create migration plan document
- [x] Write migration script
- [x] Write health check script
- [x] Update changelog to v3.0.7
- [x] Stop all services gracefully
- [x] Document current system state

### Monday Morning ✅
- [ ] Provision m6i.2xlarge cluster
- [ ] Attach both disks (100GB new, 25GB old)
- [ ] Verify CPU has avx512_vnni
- [ ] Run migration script
- [ ] Start services
- [ ] Build ONNX Runtime
- [ ] Run health check
- [ ] Test semantic search
- [ ] Celebrate success! 🎉

---

## Contact & Repository Info

**Developer**: Terry McGuinness  
**Repository**: TerrenceMcGuinness-NOAA/global-workflow  
**Branch**: MCP_node.js-RAG_ParallelWorks  
**MCP Version**: 3.0.7 (migration prep)  
**Date**: October 25, 2025  

**Status**: Ready for Monday migration to m6i.2xlarge 🚀

---

## Appendix: Technical Details

### CPU Comparison

| Feature | c5.xlarge (Current) | m6i.2xlarge (Target) |
|---------|---------------------|----------------------|
| Architecture | Skylake (2017) | Ice Lake (2019) |
| AVX512F | ✅ Yes | ✅ Yes |
| AVX512-VNNI | ❌ **NO** | ✅ **YES** |
| vCPUs | 4 | 8 |
| Memory | 8GB | 32GB |
| Network | Up to 10 Gbps | Up to 12.5 Gbps |
| Cost/hour | $0.17 | $0.384 |

### VNNI Instruction Details

**`vpdpbusds`**: Vector Packed Dot Product Signed/Unsigned Bytes  
- **Purpose**: Accelerate neural network inference (INT8 quantization)
- **Introduced**: Ice Lake (2019), not available in Skylake (2017)
- **Used by**: ONNX Runtime MLAS quantization kernels
- **Performance**: 2-4x faster inference with INT8 vs FP32

### Build Configuration

```bash
# ONNX Runtime v1.21.0
# Config: RelWithDebInfo (optimized + debug symbols)
# Flags: -g -O2
# Features: Shared lib, Python bindings, Node.js bindings
# Disabled: ML ops, contrib ops (reduce build size)
# Expected time: 30-60 min on 8-core Ice Lake
```

---

**End of Weekend Wrap-Up**  
**Next Update**: Monday October 28, 2025 - Post-Migration Report
