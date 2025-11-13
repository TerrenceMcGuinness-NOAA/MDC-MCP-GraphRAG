#!/bin/bash
# Monitor spack installation progress
# Usage: ./monitor_spack_install.sh

LOGFILE="/mcp_rag_eib/mcp_server_node/logs/spack_install_monitor.log"
mkdir -p "$(dirname "$LOGFILE")"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting spack installation monitor" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

while true; do
    # Count running spack processes
    RUNNING=$(ps aux | grep "spack install" | grep -v grep | wc -l)
    
    if [ "$RUNNING" -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [COMPLETE] All spack installations finished!" | tee -a "$LOGFILE"
        echo "" | tee -a "$LOGFILE"
        
        # Verify installed packages
        echo "[INFO] Verifying installed packages..." | tee -a "$LOGFILE"
        spack find py-numpy py-torch py-transformers py-beautifulsoup4 py-lxml py-requests py-aiohttp py-nltk | tee -a "$LOGFILE"
        
        break
    else
        TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
        echo "[${TIMESTAMP}] [IN PROGRESS] ${RUNNING} spack installation(s) still running..." | tee -a "$LOGFILE"
        
        # Show which packages are being installed
        ps aux | grep "spack install" | grep -v grep | awk '{for(i=14;i<=NF;i++) printf "%s ", $i; print ""}' | tee -a "$LOGFILE"
        echo "" | tee -a "$LOGFILE"
    fi
    
    # Wait 2 minutes before next check
    sleep 120
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monitor script completed" | tee -a "$LOGFILE"
