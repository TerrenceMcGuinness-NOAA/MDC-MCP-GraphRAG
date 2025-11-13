#!/bin/bash

# Comprehensive Crawl Monitor Script
# Usage: ./monitor-comprehensive-crawl.sh [lines]

LOGFILE="/contrib/Terry.McGuinness/opt/mcp-server/comprehensive-crawl.log"
PIDFILE="/contrib/Terry.McGuinness/opt/mcp-server/comprehensive-crawl.pid"
LINES=${1:-40}

echo "=========================================="
echo "Comprehensive Documentation Crawl Monitor"
echo "=========================================="
echo ""

# Check if process is running
if [[ -f "$PIDFILE" ]]; then
    PID=$(cat "$PIDFILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "✅ Process Status: RUNNING (PID: $PID)"

        # Get process info
        RUNTIME=$(ps -p "$PID" -o etime= | tr -d ' ')
        MEM=$(ps -p "$PID" -o rss= | awk '{printf "%.1f MB", $1/1024}')
        CPU=$(ps -p "$PID" -o %cpu= | tr -d ' ')

        echo "   Runtime: $RUNTIME"
        echo "   Memory: $MEM"
        echo "   CPU: ${CPU}%"
    else
        echo "⚠️  Process Status: COMPLETED or STOPPED"
        echo "   Check log file for completion status"
    fi
else
    echo "⚠️  No PID file found"
fi

echo ""
echo "=========================================="
echo "Log File: $LOGFILE"
echo "=========================================="
echo ""

# Show log tail
if [[ -f "$LOGFILE" ]]; then
    echo "Last $LINES lines of log:"
    echo "------------------------------------------"
    tail -n "$LINES" "$LOGFILE"
    echo "------------------------------------------"
    echo ""

    # Summary statistics
    TOTAL_LINES=$(wc -l < "$LOGFILE")
    LOG_SIZE=$(du -h "$LOGFILE" | cut -f1)

    echo "Log Statistics:"
    echo "   Total lines: $TOTAL_LINES"
    echo "   Log size: $LOG_SIZE"

    # Crawl progress stats
    READTHEDOCS_COUNT=$(grep -c "✓ Crawled:.*documentation" "$LOGFILE" 2>/dev/null || echo "0")
    WIKI_COUNT=$(grep -c "✓ Wiki page:" "$LOGFILE" 2>/dev/null || echo "0")
    GITHUB_COUNT=$(grep -c "✓ Fetched:" "$LOGFILE" 2>/dev/null || echo "0")

    echo ""
    echo "Crawl Progress:"
    echo "   ReadTheDocs pages: $READTHEDOCS_COUNT"
    echo "   GitHub wiki pages: $WIKI_COUNT"
    echo "   GitHub files: $GITHUB_COUNT"

    # Check current phase
    if grep -q "Phase 1: ReadTheDocs Sites" "$LOGFILE" 2>/dev/null; then
        LAST_PHASE=$(grep "Phase [0-9]:" "$LOGFILE" | tail -1)
        echo "   Current: $LAST_PHASE"
    fi

    # Check for EE2 docs
    if grep -q "nws-hpc-standards" "$LOGFILE" 2>/dev/null; then
        echo "   ✅ EE2 documentation is being crawled"
    else
        echo "   ⏳ EE2 documentation not yet reached"
    fi

    # Check for errors
    ERROR_COUNT=$(grep -i "error\|failed\|exception" "$LOGFILE" | grep -v "GitHub API error" | wc -l)
    if [[ $ERROR_COUNT -gt 0 ]]; then
        echo "   ⚠️  Errors found: $ERROR_COUNT"
    else
        echo "   ✅ No errors detected"
    fi

    # Check for completion
    if grep -q "COMPREHENSIVE Knowledge Base Generation Complete" "$LOGFILE" 2>/dev/null; then
        echo "   ✅ *** CRAWL COMPLETED ***"

        # Extract final stats
        TOTAL_DOCS=$(grep "Total documents processed:" "$LOGFILE" | tail -1 | awk '{print $NF}')
        TOTAL_CHUNKS=$(grep "Total chunks with embeddings:" "$LOGFILE" | tail -1 | awk '{print $NF}')
        TOTAL_WORDS=$(grep "Total words indexed:" "$LOGFILE" | tail -1 | awk '{print $NF}')

        if [[ -n "$TOTAL_DOCS" ]]; then
            echo ""
            echo "Final Results:"
            echo "   Documents: $TOTAL_DOCS"
            echo "   Chunks: $TOTAL_CHUNKS"
            echo "   Words: $TOTAL_WORDS"
        fi
    fi
else
    echo "❌ Log file not found: $LOGFILE"
fi

echo ""
echo "=========================================="
echo "Commands:"
echo "  Watch log: tail -f $LOGFILE"
echo "  Monitor: watch -n 10 ./monitor-comprehensive-crawl.sh"
echo "  Stop: kill -TERM $PID"
echo "=========================================="
