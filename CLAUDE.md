# jama-cli

CLI and MCP server for Jama requirements management. Published on PyPI as `jama-cli`.

## Tech Stack

- **Python 3.10+**, Poetry build system
- **CLI**: Typer + Rich (table/json/csv/yaml output)
- **MCP server**: stdio + HTTP modes with OpenAPI docs
- **Core**: aiohttp, py-jama-rest-client, Pydantic 2, loguru
- **Testing**: pytest, pytest-asyncio, pytest-cov, pytest-mock, pytest-xdist
- **Linting**: ruff, black, isort, mypy (strict mode)

## Project Structure

```
jama_cli/                 # CLI package
  main.py                 # Entry point (Typer app)
  commands/               # 15 command modules (items, projects, trace, diff, etc.)
  core/client.py          # Jama API client wrapper
  models/                 # Pydantic models
  config.py               # Multi-profile config management
  output/                 # Output formatters
jama_mcp_server/          # MCP server package (70 operations)
  api/                    # HTTP API layer
  core/                   # Server core logic
  config.py               # MCP server config
  models/                 # MCP-specific models
tests/                    # Test suite
scripts/                  # Utility scripts
```

## Commands

```bash
poetry install                       # Install deps
poetry run jama --help               # CLI help
poetry run pytest                    # Run tests
poetry run pytest -x --tb=short      # Quick test run
poetry run ruff check .              # Lint
poetry run black --check .           # Format check
poetry run mypy jama_cli             # Type check
poetry run isort --check-only .      # Import order check
```

## Configuration

```bash
jama config init                     # Interactive setup
# Or: cp config.yml.example config.yml and edit
# Env vars: JAMA_URL, JAMA_CLIENT_ID, JAMA_CLIENT_SECRET
```

## Key Rules

- This is a published PyPI package — maintain backward compatibility
- CLI entry point: `jama` (defined in `[tool.poetry.scripts]`)
- Both `jama_cli` and `jama_mcp_server` are included in the package
- Strict mypy: `disallow_untyped_defs`, `disallow_incomplete_defs`, `disallow_any_generics`
- Line length: 100 (black + isort configured)
- Unofficial community project — not affiliated with Jama Software

## Do NOT

- Break the public CLI interface (commands, flags, output formats)
- Mix jama_cli and jama_mcp_server imports — they are separate packages
- Skip type annotations — mypy strict mode will catch it
- Hardcode Jama credentials — use config profiles or env vars
- Add deps without checking py-jama-rest-client compatibility (Python 3.10+)
