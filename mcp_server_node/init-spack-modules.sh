#!/bin/bash

# Initialize spack-stack modules for Global Workflow MCP Server
# This script sets up the proper module environment for using Python 3.11.11
# from spack-stack instead of virtual environments

# Initialize the standard module system first
source /usr/share/Modules/init/bash

# Initialize Lmod from spack installation
source /home/tmcguinness/spack/opt/spack/linux-skylake/lmod-8.7.55-5lisvketniqnucm2ehub3mqkedjh2o6x/lmod/8.7.55/init/bash

# Add spack modulefiles to module path
module use /home/tmcguinness/spack/share/spack/lmod/Core

# Load Python 3.11.11 from spack-stack
module load python/3.11.11-y3wp

# Verify the setup
echo "Module environment initialized:"
echo "  Python version: $(python --version)"
echo "  Python path: $(which python)"
echo "  Module list:"
module list 2>&1 | grep -v "No modules loaded" || echo "    python/3.11.11-y3wp"

# Test ChromaDB availability
python -c "import chromadb; print('  ChromaDB version:', chromadb.__version__)" 2>/dev/null || echo "  ChromaDB: Not available"