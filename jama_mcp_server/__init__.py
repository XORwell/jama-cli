"""
Jama MCP Server package.

A Model Context Protocol (MCP) server for Jama with read and write capabilities.
"""

__version__ = "0.1.1"
__author__ = "Christian Nennemann"
__license__ = "MIT"

from jama_mcp_server.models import JamaConfig, MCPRequest, MCPResponse

__all__ = ["JamaConfig", "MCPRequest", "MCPResponse", "__version__"]
