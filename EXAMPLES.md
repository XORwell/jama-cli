# Jama CLI Examples

Real-world examples and common workflows.

## Table of Contents

- [Getting Started](#getting-started)
- [Working with Items](#working-with-items)
- [Traceability Analysis](#traceability-analysis)
- [Baselines & Version History](#baselines--version-history)
- [Search & Filtering](#search--filtering)
- [Data Migration](#data-migration)
- [Scripting & Automation](#scripting--automation)
- [MCP Server Integration](#mcp-server-integration)

---

## Getting Started

### Configure your connection

```bash
# Interactive setup (recommended)
jama config init

# Or add profile directly
jama config add prod \
  --url https://company.jamacloud.com \
  --oauth \
  --client-id $JAMA_CLIENT_ID \
  --client-secret $JAMA_CLIENT_SECRET

# Verify connection
jama projects list
```

### Multiple environments

```bash
# Add multiple profiles
jama config add production --url https://prod.jamacloud.com --api-key $PROD_KEY
jama config add staging --url https://staging.jamacloud.com --api-key $STAGING_KEY

# Switch between them
jama -p production projects list
jama -p staging projects list

# Set default
jama config set-default production
```

---

## Working with Items

### List items (with pagination)

```bash
# Default: first 50 items (fast)
jama items list 1172

# Get more items
jama items list 1172 --limit 100

# Get ALL items (slower for large projects)
jama items list 1172 --limit 0

# Filter by item type
jama items list 1172 --type 45

# Custom columns
jama items list 1172 --fields id,documentKey,name,status,priority
```

### Get item details

```bash
# Get single item (use API ID from 'items list' output)
jama items get 1241247

# JSON output for scripting
jama items get 1241247 --output json

# Find API ID: look at 'id' column in items list, or URL after /items/
```

### Create items

```bash
# Basic item
jama items create 1172 --type 45 --name "New Requirement"

# With parent (hierarchical)
jama items create 1172 --type 45 --name "Child Req" --parent 1241247

# With description and custom fields
jama items create 1172 \
  --type 45 \
  --name "REQ-001: User Login" \
  --description "System shall support SSO authentication" \
  --fields '{"priority": "High", "status": "Draft"}'
```

### Update items

```bash
# Update name
jama items update 1241247 --name "Updated Name"

# Update custom field
jama items update 1241247 --field status=Approved

# Update multiple fields
jama items update 1241247 \
  --field status=Approved \
  --field priority=High \
  --field assignee=john.doe
```

### Delete items

```bash
# With confirmation prompt
jama items delete 1241247

# Skip confirmation (use in scripts)
jama items delete 1241247 --force
```

---

## Traceability Analysis

### Generate traceability matrix

```bash
# Show all relationships in project
jama trace matrix 1172

# Filter: requirements → test cases
jama trace matrix 1172 --source 45 --target 67

# Show only items WITHOUT traces (coverage gaps)
jama trace matrix 1172 --untraced

# Export to CSV for reports
jama trace matrix 1172 --format csv > trace_matrix.csv
```

### Coverage analysis

```bash
# Coverage summary by item type
jama trace coverage 1172

# Shows for each type:
# - Total items
# - Items with upstream traces
# - Items with downstream traces
# - Coverage percentages
```

### Trace tree visualization

```bash
# Show full trace tree for an item
jama trace tree 1241247

# Upstream only (what traces TO this item)
jama trace tree 1241247 --direction upstream

# Downstream only (what this item traces TO)
jama trace tree 1241247 --direction downstream

# Limit depth
jama trace tree 1241247 --depth 2
```

---

## Baselines & Version History

### Work with baselines

```bash
# List all baselines in project
jama baseline list 1172

# Get baseline details
jama baseline get 100

# List items in a baseline
jama baseline items 100

# Compare two baselines (show changes)
jama baseline diff 100 101
# Shows: +Added, ~Modified, -Removed items
```

### View item history

```bash
# List all versions of an item
jama history list 1241247

# Get specific version
jama history get 1241247 3

# Compare two versions (show field changes)
jama history diff 1241247 1 3
```

---

## Search & Filtering

### Search items

```bash
# Search across all projects
jama search items "authentication"

# Search in specific project
jama search items "login" --project 1172

# Search by document key pattern
jama search items "REQ-" --field documentKey

# Regex search
jama search items "^REQ-\\d{3}" --regex

# Search specific item type
jama search items "user" --type 45 --project 1172
```

### Compare projects

```bash
# Compare items between two projects
jama diff projects 1172 1174

# Compare specific item type
jama diff projects 1172 1174 --type 45

# Quick count comparison
jama diff count 1172 1174

# Compare across instances
jama diff projects 123 456 --from staging --to production
```

---

## Data Migration

### Export data

```bash
# Fast export (items only, no relationships)
jama migrate export 1172 -o project_backup.json

# Limit items for quick partial export
jama migrate export 1172 --max 100 -o sample.json

# Export subtree with limit (great for large projects)
jama migrate export 1172 --parent 1241247 --max 50 -o subtree.json

# Export specific item type
jama migrate export 1172 --type 45 -o requirements.json

# Full export with relationships (slower)
jama migrate export 1172 --relationships -o full_export.json

# Export subtree with relationships
jama migrate export 1172 --parent 1241247 --relationships -o subtree_full.json
```

### Performance tips for large projects

```bash
# Fast: Use --max to limit items
jama migrate export 1172 --max 200              # First 200 items

# Fast: Export by item type (often smaller set)
jama migrate export 1172 --type 45              # Only requirements

# Fast: Export subtree instead of whole project
jama migrate export 1172 --parent 1241247       # Just this branch

# Slow: Full export with relationships
jama migrate export 1172 --relationships        # Fetches rels per item

# Combine for best results
jama migrate export 1172 --parent 1241247 --max 100 --type 45
```

### Import data

```bash
# Preview import (dry run)
jama migrate import backup.json --project 1174 --dry-run

# Import to project
jama migrate import backup.json --project 1174

# Inspect export file
jama migrate info backup.json
```

### Clone within instance

```bash
# Clone project items
jama migrate clone 1172 1174 --dry-run
jama migrate clone 1172 1174

# Clone subtree
jama migrate clone 1172 1174 --source-parent 1241247 --target-parent 1241300
```

### Copy between instances

```bash
# Copy from staging to production
jama migrate copy 123 456 --from staging --to production --dry-run
jama migrate copy 123 456 --from staging --to production
```

---

## Scripting & Automation

### Export to CSV for reporting

```bash
# Requirements list
jama items list 1172 --type 45 --output csv > requirements.csv

# Traceability matrix
jama trace matrix 1172 --format csv > traceability.csv

# All items with custom fields
jama items list 1172 --limit 0 --fields id,documentKey,name,status,priority --output csv > all_items.csv
```

### JSON processing with jq

```bash
# Get item names
jama items list 1172 --output json | jq '.[].fields.name'

# Count by status
jama items list 1172 --limit 0 --output json | jq 'group_by(.fields.status) | map({status: .[0].fields.status, count: length})'

# Extract specific item field
jama items get 1241247 --output json | jq '.fields.description'
```

### Batch operations

```bash
# Update multiple items from file
cat item_ids.txt | while read id; do
  jama items update $id --field status=Approved
done

# Export multiple projects
for project in 1172 1174 1176; do
  jama migrate export $project -o "project_${project}.json"
done
```

### CI/CD integration

```bash
#!/bin/bash
# Verify all requirements have test coverage

UNTRACED=$(jama trace matrix $PROJECT_ID --untraced --format json | jq length)

if [ "$UNTRACED" -gt 0 ]; then
  echo "ERROR: $UNTRACED requirements without test coverage"
  jama trace matrix $PROJECT_ID --untraced
  exit 1
fi

echo "All requirements have test coverage"
```

---

## MCP Server Integration

### Claude Desktop / Cline

Add to `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jama": {
      "command": "jama",
      "args": ["serve", "--stdio"],
      "env": {
        "JAMA_URL": "https://company.jamacloud.com",
        "JAMA_API_KEY": "your-api-key"
      }
    }
  }
}
```

Then ask Claude:
- "List all projects in Jama"
- "Show requirements in project 1172"
- "Find all items related to authentication"
- "What test cases cover REQ-001?"

### HTTP Server

```bash
# Start server
jama serve --port 8000

# With authentication
jama serve --port 8000 --api-key $MCP_API_KEY

# API documentation
open http://localhost:8000/api/docs
```

### API calls

```bash
# Health check
curl http://localhost:8000/health

# List projects
curl -X POST http://localhost:8000/mcp/invoke \
  -H "Content-Type: application/json" \
  -d '{"method": "get_projects", "params": {}}'

# Get items
curl -X POST http://localhost:8000/mcp/invoke \
  -H "Content-Type: application/json" \
  -d '{"method": "get_items", "params": {"project_id": 1172}}'
```

---

## Tips & Tricks

### Performance

```bash
# Use --limit for large projects
jama items list 1172 --limit 50      # Fast (default)
jama items list 1172 --limit 0       # All items (slower)

# Cache is automatic - repeated queries are faster
jama items list 1172  # First call: API request
jama items list 1172  # Second call: from cache

# Clear cache if needed
jama config cache --clear
```

### Finding IDs

```bash
# Project ID: from projects list
jama projects list

# Item API ID: from items list (id column) or URL
jama items list 1172
# URL example: .../items/1241247 → API ID is 1241247

# Item Type ID: from types list
jama types list
```

### Output formats

```bash
# Table (default) - human readable
jama items list 1172

# JSON - for scripting/jq
jama items list 1172 --output json

# CSV - for spreadsheets
jama items list 1172 --output csv > items.csv

# YAML - for config files
jama items list 1172 --output yaml
```

### Debugging

```bash
# Verbose output
jama -v items list 1172       # Warnings
jama -vv items list 1172      # Info
jama -vvv items list 1172     # Debug (shows API calls)

# Quiet mode (errors only)
jama -q items list 1172
```
