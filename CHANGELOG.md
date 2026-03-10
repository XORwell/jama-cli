# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2] - 2026-03-10

### Fixed
- Restored GHCR Docker badge in README
- Signed all commits with YubiKey SSH key

## [0.1.0] - 2026-03-10

### Initial Public Release

#### CLI (`jama`)
- **Full CRUD Operations**: Create, Read, Update, Delete Jama items
- **70 Jama API Operations**: Complete coverage of Jama REST API
- **Multiple Auth Methods**: OAuth2, API tokens, or username/password
- **Multi-Server Profiles**: YAML config with named profiles and `--profile` switching
- **Rich Output**: Table, JSON, and plain text output formats

#### MCP Server
- **Dual Protocol Support**: stdio MCP (for Claude Desktop, Cline) and HTTP REST API
- **SSE Streaming**: Real-time Server-Sent Events via `/v1/sse`
- **Batch Operations**: Execute multiple operations via `/v1/batch`
- **OpenAPI Documentation**: Interactive Swagger UI at `/api/docs`

#### Read Operations
- Projects & Items
- Relationships & Dependencies
- Item Types & Metadata
- Pick Lists & Options
- Tags
- Test Cycles & Runs
- Baselines & Versions
- Users & Filters

#### Write Operations
- Create/Update/Delete items
- Create/Delete relationships
- Item locking
- File attachments
- Test run updates
- User management

#### Data Migration
- **Export Command**: `jama migrate export` - Export items to JSON with hierarchy preservation
- **Import Command**: `jama migrate import` - Import items from JSON with type mapping support
- **Clone Command**: `jama migrate clone` - Clone items within the same Jama instance
- **Copy Command**: `jama migrate copy` - Copy items between different Jama instances
- **Info Command**: `jama migrate info` - Inspect export file contents

#### Search & Diff
- **Search Command**: `jama search` - Find items by text or regex
- **Diff Command**: `jama diff` - Compare items between projects or instances

#### Performance
- **Caching Layer**: In-memory + disk cache for frequently accessed data
- **Cache Management**: `jama config cache` command to view stats and clear cache

#### Production Readiness
- **API Authentication**: Bearer token authentication for HTTP server
- **Rate Limiting**: Built-in rate limiting (100 requests/60 seconds per IP)
- **Security Headers**: Standard security headers on all responses
- **Graceful Shutdown**: Proper signal handling for clean shutdown
- **Kubernetes Probes**: `/ready` and `/live` endpoints
- **Structured Logging**: JSON log format option for log aggregation
- **Docker Support**: Multi-stage build with development and production images

---

[0.1.0]: https://github.com/XORwell/jama-cli/releases/tag/v0.1.0
