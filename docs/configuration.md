# Configuration Guide

## Configuration File Location

The Jama MCP Server looks for configuration in the following locations (in order of priority):

1. **Explicitly specified path**: `--config /path/to/config.yml`
2. **Environment variable**: `JAMA_CONFIG=/path/to/config.yml`
3. **User home directory**: `~/.jama/config.yml` ✨ **Recommended for installed package**
4. **Current directory**: `./config.yml` or `./config.yaml`
5. **Command-line arguments**: Individual flags override all file-based configs

### Recommended Setup by Use Case

**Development (local clone):**
```bash
# Keep config.yml in project directory
cp config.yml.example config.yml
# Edit and use
```

**Installed Package (via pip/poetry):**
```bash
# Create user-level config directory
mkdir -p ~/.jama
cp config.yml.example ~/.jama/config.yml
# Edit ~/.jama/config.yml with your credentials
```

**CI/CD or Temporary:**
```bash
# Use environment variable to point to config
export JAMA_CONFIG=/secure/path/config.yml
# OR use command-line arguments directly
jama --profile prod serve
```

## Multi-Server Configuration with YAML

YAML is the **primary and recommended** configuration method. It supports multiple servers and is more maintainable than environment variables.

### Setup

1. **Create your configuration file:**
   ```bash
   cp config.yml.example config.yml
   ```

2. **Edit `config.yml` with your server credentials:**
   ```yaml
   # Default server to use
   default_server: sandbox

   # Server configurations
   servers:
     sandbox:
       url: https://your-sandbox.jamacloud.com
       oauth: true
       client_id: your_client_id
       client_secret: your_client_secret
     
     production:
       url: https://your-production.jamacloud.com
       oauth: true
       client_id: your_production_client_id
       client_secret: your_production_client_secret
   ```

3. **The file is automatically protected:**
   - `config.yml` is in `.gitignore` and will never be committed
   - Your credentials stay on your local machine only

### Usage

**List configured servers:**
```bash
jama config list
```

**Use the default server:**
```bash
jama serve
```

**Use a specific server:**
```bash
jama serve --server production
```

**Use in stdio mode (for Claude Desktop/Cline):**
```bash
jama serve --stdio --server sandbox
```

### Authentication Methods

The configuration supports three authentication methods (in order of preference):

#### 1. OAuth Client Credentials (Recommended)
```yaml
servers:
  my-server:
    url: https://instance.jamacloud.com
    oauth: true
    client_id: your_client_id
    client_secret: your_client_secret
```

#### 2. API Key
```yaml
servers:
  my-server:
    url: https://instance.jamacloud.com
    api_key: your_api_key
```

#### 3. Username/Password
```yaml
servers:
  my-server:
    url: https://instance.jamacloud.com
    username: your_username
    password: your_password
```

## Legacy .env Configuration (Deprecated)

> ⚠️ **Note**: The `.env` file format is **deprecated** and maintained only for backward compatibility. 
> Please use `config.yml` instead, which provides better multi-server support and clarity.

<details>
<summary>Click to see legacy .env format (not recommended)</summary>

The traditional `.env` file format is still supported for single-server setups:

```bash
# Create .env file
cp .env.example .env

# Edit with your credentials
JAMA_URL=https://your-instance.jamacloud.com
JAMA_OAUTH=true
JAMA_CLIENT_ID=your_client_id
JAMA_CLIENT_SECRET=your_client_secret
```

**Limitations:**
- ❌ Only supports a single server
- ❌ Less readable than YAML
- ❌ No multi-environment support
- ❌ Harder to manage multiple credentials

**Migration to YAML:**
```bash
# Instead of .env, create config.yml:
cat > config.yml << EOF
default_server: my-server

servers:
  my-server:
    url: https://your-instance.jamacloud.com
    oauth: true
    client_id: your_client_id
    client_secret: your_client_secret
EOF
```

</details>

## Why YAML over .env?

| Feature | YAML (config.yml) | .env |
|---------|-------------------|------|
| Multiple servers | ✅ Yes | ❌ No |
| Named configurations | ✅ Yes | ❌ No |
| Nested structure | ✅ Yes | ❌ Limited |
| Comments & documentation | ✅ Yes | ⚠️ Basic |
| Server switching | ✅ `--server name` | ❌ N/A |
| Migration workflows | ✅ Easy | ❌ Complex |
| Readability | ✅ High | ⚠️ Medium |

## Command-Line Override

You can override any configuration value with command-line arguments:

```bash
jama serve \
  --jama-url https://override.jamacloud.com \
  --client-id my_client_id \
  --client-secret my_client_secret
```

This is useful for:
- Testing different credentials
- One-off connections
- CI/CD pipelines

## Configuration Priority

The system loads configuration in this order (later overrides earlier):

1. **YAML config file** (`~/.jama/config.yml` or `./config.yml`)
2. **Environment variables** (deprecated `.env` file or shell exports)
3. **Command-line arguments** (highest priority)

**Example Priority Resolution:**
```bash
# config.yml has: url: https://prod.jamacloud.com
# Environment has: JAMA_URL=https://staging.jamacloud.com
# Command-line has: --jama-url https://dev.jamacloud.com

# Result: Uses dev.jamacloud.com (command-line wins)
```

## Configuration Best Practices

### ✅ DO:

- **Use `~/.jama/config.yml`** for installed package installations
- **Use `./config.yml`** for development/local clones
- **Use YAML format** for all new configurations
- **Set `JAMA_CONFIG`** environment variable for custom locations
- **Use OAuth client credentials** when possible
- **Rotate credentials regularly**
- **Use named servers** for clarity (e.g., "prod", "sandbox", not "server1")

### ❌ DON'T:

- **Don't use `.env` files** for new setups (use YAML instead)
- **Don't mix `.env` and `config.yml`** (pick one to avoid confusion)
- **Don't commit** `config.yml` or `.env` to version control
- **Don't share credentials** in plain text
- **Don't use the same credentials** for all environments
- **Don't store credentials** in code or scripts

## Migration Scenarios

### Migrating from Server A to Server B

1. **Configure both servers in `config.yml`:**
   ```yaml
   servers:
     source:
       url: https://source.jamacloud.com
       client_id: source_client_id
       client_secret: source_client_secret
     target:
       url: https://target.jamacloud.com
       client_id: target_client_id
       client_secret: target_client_secret
   ```

2. **Run operations on each server:**
   ```bash
   # Read from source
   jama serve --server source
   
   # Write to target
   jama serve --server target
   ```

### Multiple Environments

```yaml
default_server: dev

servers:
  dev:
    url: https://dev.jamacloud.com
    client_id: dev_client_id
    client_secret: dev_client_secret
  
  staging:
    url: https://staging.jamacloud.com
    client_id: staging_client_id
    client_secret: staging_client_secret
  
  production:
    url: https://production.jamacloud.com
    client_id: prod_client_id
    client_secret: prod_client_secret
```

## Troubleshooting

**Config file not found:**
```bash
# Check current directory
ls -la config.yml

# Specify config file path explicitly
jama serve --config /path/to/config.yml
```

**Server not found:**
```bash
# List available servers
jama config list

# Use correct server name
jama serve --server <server_name>
```

**Authentication failed:**
- Verify credentials are correct in `config.yml`
- Check that OAuth is enabled if using client credentials
- Ensure URL includes `https://` and domain name
- Test credentials directly in Jama web interface

## Examples

See `config.yml.example` for complete configuration examples with all supported authentication methods and use cases.
