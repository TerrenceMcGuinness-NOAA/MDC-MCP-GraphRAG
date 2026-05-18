#!/bin/bash
################################################################################
# 05-python-spack.sh - Python and Spack module system setup
# Part of modular provisioning system v4.0.0
################################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

require_root

log_subsection "Python Environment Setup"

USER_NAME=$(get_actual_user)
USER_OWNERSHIP=$(get_ownership "${USER_NAME}")

# Ensure Python 3.11 is available
if command_exists python3.11; then
    log_info "Python 3.11 already available: $(python3.11 --version)"
else
    log_info "Installing Python 3.11..."
    dnf install -y python3.11 python3.11-devel python3.11-pip || {
        log_error "Failed to install Python 3.11"
        exit 1
    }
fi

# Set python3.11 as default python3 alternative
log_info "Configuring Python alternatives..."
alternatives --set python3 /usr/bin/python3.11 2>/dev/null || true

# Verify
log_success "Python: $(python3 --version)"
log_success "Pip: $(python3 -m pip --version)"

################################################################################
# Spack Module System
################################################################################

log_subsection "Spack Module System"

SPACK_ROOT="${PERSISTENT_ROOT}/spack"

if [[ -d "${SPACK_ROOT}" ]] && [[ -f "${SPACK_ROOT}/bin/spack" ]]; then
    log_info "Spack already installed at ${SPACK_ROOT}"
else
    log_info "Installing Spack..."
    
    # Create directory as root, then clone as user to avoid ownership issues
    mkdir -p "${SPACK_ROOT}"
    chown "${USER_OWNERSHIP}" "${SPACK_ROOT}"
    
    # Clone Spack as the target user (not root)
    run_as_user "${USER_NAME}" "git clone -c feature.manyFiles=true https://github.com/spack/spack.git ${SPACK_ROOT}" || {
        log_error "Failed to clone Spack"
        exit 1
    }
    
    log_success "Spack installed (owned by ${USER_NAME})"
fi

# Source Spack
source "${SPACK_ROOT}/share/spack/setup-env.sh"

log_success "Spack: $(spack --version)"

# Configure Spack for Lmod
log_info "Configuring Spack for Lmod modules..."

# Create modules.yaml if it doesn't exist
SPACK_CONFIG="${SPACK_ROOT}/etc/spack"
mkdir -p "${SPACK_CONFIG}"

if [[ ! -f "${SPACK_CONFIG}/modules.yaml" ]]; then
    cat > "${SPACK_CONFIG}/modules.yaml" << 'EOF'
modules:
  default:
    enable:
      - lmod
    lmod:
      core_compilers:
        - gcc@11.5.0
      hierarchy:
        - mpi
      hash_length: 0
      all:
        autoload: direct
EOF
    log_info "Created modules.yaml"
fi

################################################################################
# Pip-Only Python Dependencies
################################################################################

log_subsection "Pip-Only Python Dependencies"

# These packages are NOT available in Spack and must be installed via pip
PIP_PACKAGES=(
    "chromadb"
    "sentence-transformers"
)

log_info "Installing pip-only packages (not available in Spack)..."

for pkg in "${PIP_PACKAGES[@]}"; do
    log_info "Installing ${pkg}..."
    python3 -m pip install --user "${pkg}" || log_warning "Failed to install ${pkg}"
done

# Verify ChromaDB
if python3 -c "import chromadb; print(f'ChromaDB {chromadb.__version__}')" 2>/dev/null; then
    log_success "ChromaDB: $(python3 -c 'import chromadb; print(chromadb.__version__)')"
else
    log_warning "ChromaDB import failed"
fi

# Verify sentence-transformers
if python3 -c "import sentence_transformers; print(f'sentence-transformers {sentence_transformers.__version__}')" 2>/dev/null; then
    log_success "sentence-transformers: $(python3 -c 'import sentence_transformers; print(sentence_transformers.__version__)')"
else
    log_warning "sentence-transformers import failed"
fi

log_success "Python and Spack setup complete"

exit 0
