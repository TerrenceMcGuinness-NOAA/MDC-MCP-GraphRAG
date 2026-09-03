*Tenant: gw*
*Branch: develop*

# EE2 Standards Search: error handling err_chk

Found 1 standards

## Standard 1
**Similarity:** 88.0%
**Category:** error_handling

Production scripts must call err_chk after each command and err_exit on failure; set -eu and set -e are NOT required.

**Example:**
```
err_chk
export err=$?; err_chk
```

---
