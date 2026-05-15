#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Server for Global Workflow
Provides context about the global-workflow repository structure and functionality
"""

import json
import sys
import asyncio
from typing import Any, Dict, List, Optional
import os
import logging
from pathlib import Path

# Set up logging for debugging (writes to stderr so it doesn't interfere with MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

class GlobalWorkflowMCPServer:
    """MCP Server for Global Workflow repository"""
    
    def __init__(self):
        """Initialize the MCP server"""
        self.repo_root = Path(__file__).parent
        self.logger = logging.getLogger("GlobalWorkflowMCP")
        self.logger.info(f"Initializing MCP server for repository: {self.repo_root}")
        
        self.tools = [
            {
                "name": "get_workflow_info",
                "description": "Get information about the global workflow system",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "component": {
                            "type": "string",
                            "description": "Component to get info about (jobs, scripts, configs, etc.)"
                        }
                    }
                }
            },
            {
                "name": "list_job_scripts",
                "description": "List available job scripts in the workflow",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_config_info",
                "description": "Get configuration information for different systems",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "system": {
                            "type": "string",
                            "description": "System name (hera, orion, wcoss2, etc.)"
                        }
                    }
                }
            }
        ]
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming MCP requests"""
        method = request.get("method")
        params = request.get("params", {})
        
        self.logger.info(f"Handling request: {method}")
        
        if method == "initialize":
            self.logger.info("Server initialized successfully")
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "global-workflow-mcp",
                    "version": "1.0.0"
                }
            }
        
        elif method == "tools/list":
            self.logger.info(f"Listing {len(self.tools)} available tools")
            return {"tools": self.tools}
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            self.logger.info(f"Calling tool: {tool_name} with args: {arguments}")
            
            if tool_name == "get_workflow_info":
                return await self._get_workflow_info(arguments)
            elif tool_name == "list_job_scripts":
                return await self._list_job_scripts(arguments)
            elif tool_name == "get_config_info":
                return await self._get_config_info(arguments)
        
        self.logger.warning(f"Unknown method: {method}")
        return {"error": f"Unknown method: {method}"}
    
    async def _get_workflow_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get workflow information"""
        component = args.get("component")
        
        info = {
            "overview": "NOAA Global Workflow - Operational weather prediction system",
            "description": "The Global Workflow is NOAA's end-to-end numerical weather prediction system that runs operationally to produce GFS, GDAS, and GEFS forecasts.",
            "workflow_structure": {
                "data_assimilation": "GDAS (Global Data Assimilation System) - combines observations with model background",
                "deterministic_forecast": "GFS (Global Forecast System) - single deterministic forecast",
                "ensemble_forecast": "GEFS (Global Ensemble Forecast System) - probabilistic ensemble forecasts",
                "workflow_engine": "Rocoto XML-based workflow management with job dependencies"
            },
            "components": {
                "jobs": "Job scripts (J*) for various workflow tasks - batch job submission scripts",
                "scripts": "Execution scripts (ex*) for workflow execution - actual implementation logic",
                "ush": "Utility shell scripts and common functions",
                "parm": "Parameter files, configurations, and templates",
                "fix": "Fixed input data files, lookup tables, and static datasets",
                "sorc": "Source code directories for models and utilities",
                "modulefiles": "Environment module files for different HPC systems",
                "env": "System-specific environment configuration files"
            },
            "systems": ["hera", "orion", "hercules", "wcoss2", "gaeac5", "gaeac6"],
            "runs": {
                "gfs": "Global Forecast System - deterministic weather forecasts",
                "gdas": "Global Data Assimilation System - analysis and reanalysis",
                "gefs": "Global Ensemble Forecast System - ensemble probabilistic forecasts"
            },
            "rocoto": "Workflow management using Rocoto XML with job dependencies and scheduling",
            "directory_structure": {
                "/jobs": "Production job scripts (JGDAS_*, JGFS_*, JGLOBAL_*)",
                "/scripts": "Execution scripts (exgdas_*, exgfs_*, exglobal_*)",
                "/dev/jobs": "Development job scripts",
                "/ush": "Utility scripts and functions",
                "/parm": "Configuration files and parameters",
                "/fix": "Static input data and lookup tables",
                "/sorc": "Source code for UFS, GSI, and other components"
            }
        }
        
        if component and component in info:
            return {"content": [{"type": "text", "text": str(info[component])}]}
        else:
            return {"content": [{"type": "text", "text": json.dumps(info, indent=2)}]}
    
    async def _list_job_scripts(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List available job scripts"""
        jobs_dir = self.repo_root / "jobs"
        if not jobs_dir.exists():
            return {"content": [{"type": "text", "text": "Jobs directory not found"}]}
        
        job_scripts = []
        for job_file in jobs_dir.glob("J*"):
            if job_file.is_file():
                job_scripts.append(job_file.name)
        
        job_list = "\n".join(sorted(job_scripts))
        return {"content": [{"type": "text", "text": f"Available job scripts:\n{job_list}"}]}
    
    async def _get_config_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get configuration information"""
        system = args.get("system", "general")
        
        config_info = {
            "hera": "NOAA RDHPCS Hera system configuration",
            "orion": "NOAA RDHPCS Orion system configuration", 
            "hercules": "NOAA RDHPCS Hercules system configuration",
            "wcoss2": "NOAA WCOSS2 operational system configuration",
            "general": "Configuration files are in parm/ directory"
        }
        
        info = config_info.get(system, f"Configuration for {system}")
        return {"content": [{"type": "text", "text": info}]}

async def main():
    """Main MCP server loop"""
    server = GlobalWorkflowMCPServer()
    
    # Read from stdin and write to stdout for MCP protocol
    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            
            request = json.loads(line.strip())
            response = await server.handle_request(request)
            
            # Add request ID if present
            if "id" in request:
                response["id"] = request["id"]
            
            print(json.dumps(response))
            sys.stdout.flush()
            
        except json.JSONDecodeError:
            continue
        except Exception as e:
            error_response = {
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
            if "id" in locals() and "request" in locals() and "id" in request:
                error_response["id"] = request["id"]
            
            print(json.dumps(error_response))
            sys.stdout.flush()

if __name__ == "__main__":
    asyncio.run(main())
