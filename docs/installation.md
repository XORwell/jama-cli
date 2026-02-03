# Installation and Setup

The Jama MCP Server can be installed via different methods depending on your use case.

## Quick Install (Recommended)

### For End Users

**1. Install the package:**
```bash
pip install jama-cli
```

**2. Create your configuration file:**
```bash
# Create config directory in your home folder
mkdir -p ~/.jama

# Create config file (recommended location for installed packages)
cat > ~/.jama/config.yml << 'EOF'
default_server: my-server

servers:
  my-server:
    url: https://your-instance.jamacloud.com
    oauth: true
    client_id: your_client_id
    client_secret: your_client_secret
EOF
```

**3. Verify installation:**
```bash
jama config list
jama serve
```

**Why `~/.jama/config.yml`?**
- ✅ Works from any directory
- ✅ Survives package updates
- ✅ Standard Unix/Linux convention
- ✅ Keeps credentials separate from code

### For Developers

**1. Clone and install:**
```bash
git clone https://github.com/XORwell/jama-cli.git
cd jama-cli
poetry install
```

**2. Create local config:**
```bash
# Copy example and edit (stays in project dir, already in .gitignore)
cp config.yml.example config.yml
# Edit config.yml with your credentials
```

**3. Run:**
```bash
poetry run jama serve
```

## Installation Methods

### Using Poetry

```bash
poetry add jama-cli
```

### Using Pip

```bash
pip install jama-cli
```

## Configuration File Locations

After installation, the server looks for `config.yml` in this order:

1. **Explicit path**: `jama --profile <name>` or via config file
2. **Environment variable**: `export JAMA_CONFIG=/path/to/config.yml`
3. **User home**: `~/.jama/config.yml` ⭐ **Recommended for pip/poetry install**
4. **Current directory**: `./config.yml` ⭐ **Recommended for development**

### Location Decision Guide

| Scenario | Recommended Location | Why |
|----------|---------------------|-----|
| Installed via pip/poetry | `~/.jama/config.yml` | Works from anywhere, survives updates |
| Local development | `./config.yml` | Project-specific, already gitignored |
| CI/CD | `$JAMA_CONFIG` env var | Flexible, secure secret management |
| Docker | Volume mount | `/app/config.yml` or custom path |

## Complete Setup Examples

### Example 1: Production Install

```bash
# Install
pip install jama-cli

# Create config
mkdir -p ~/.jama
cat > ~/.jama/config.yml << 'EOF'
default_server: production

servers:
  production:
    url: https://prod.jamacloud.com
    oauth: true
    client_id: prod_client_id
    client_secret: prod_client_secret
EOF

# Secure the config file
chmod 600 ~/.jama/config.yml

# Test
jama config list
jama serve
```

### Example 2: Multi-Environment Setup

```bash
# Install
pip install jama-cli

# Create multi-server config
mkdir -p ~/.jama
cat > ~/.jama/config.yml << 'EOF'
default_server: sandbox

servers:
  sandbox:
    url: https://sandbox.jamacloud.com
    oauth: true
    client_id: sandbox_id
    client_secret: sandbox_secret
  
  production:
    url: https://prod.jamacloud.com
    oauth: true
    client_id: prod_id
    client_secret: prod_secret
EOF

# List all profiles
jama config list

# Use specific server
jama --profile production serve
```

## Development Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/jama-cli.git
cd jama-cli
```

2. Install dependencies with Poetry:
```bash
poetry install
```

3. Activate the virtual environment:
```bash
poetry shell
```

## Dev Container

If you're using Visual Studio Code with the Dev Containers extension:

1. Open the repository folder in VS Code
2. When prompted, click "Reopen in Container"
3. Wait for the container to build and initialize
4. All dependencies will be automatically installed
