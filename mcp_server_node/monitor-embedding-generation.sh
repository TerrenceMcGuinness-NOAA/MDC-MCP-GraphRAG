#!/bin/bash

# Embedding Generation Monitor Script
# Usage: ./monitor-embedding-generation.sh [lines]

LOGFILE="/contrib/Terry.McGuinness/opt/mcp-server/embedding-generation.log"
PIDFILE="/contrib/Terry.McGuinness/opt/mcp-server/embedding-generation.pid"
LINES=${1:-30}

echo "=========================================="
echo "Embedding Generation Monitor"
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

    # Check for errors
    ERROR_COUNT=$(grep -i "error\|failed\|exception" "$LOGFILE" | wc -l)
    if [[ $ERROR_COUNT -gt 0 ]]; then
        echo "   ⚠️  Errors found: $ERROR_COUNT"
    else
        echo "   ✅ No errors detected"
    fi

    # Check for completion
    if grep -q "completed\|finished\|success" "$LOGFILE" 2>/dev/null; then
        echo "   ✅ Completion markers found in log"
    fi
else
    echo "❌ Log file not found: $LOGFILE"
fi

echo ""
echo "=========================================="
echo "Commands:"
echo "  Watch log: tail -f $LOGFILE"
echo "  Stop process: kill -TERM $PID"
echo "  Monitor: watch -n 5 ./monitor-embedding-generation.sh"
echo "=========================================="
