# Contributing to Jama MCP Server

We love your input! We want to make contributing to Jama MCP Server as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features
- Becoming a maintainer

## Development Process

We use GitHub to host code, to track issues and feature requests, as well as accept pull requests.

### Pull Requests

1. Fork the repo and create your branch from `main`.
2. If you've added code that should be tested, add tests.
3. If you've changed APIs, update the documentation.
4. Ensure the test suite passes.
5. Make sure your code lints.
6. Issue that pull request!

### Development Setup

1. Clone the repository
2. Install Poetry (if not already installed)
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```
3. Install dependencies
   ```bash
   poetry install
   ```
4. Set up pre-commit hooks
   ```bash
   pre-commit install
   ```

### Code Style

We use the following tools to ensure code quality:

- **Black** for code formatting
- **isort** for import sorting
- **mypy** for static type checking
- **flake8** for linting

All of these checks are run in the CI pipeline for each pull request.

## Testing

Please write tests for any new features or bug fixes. Run the tests with:

```bash
poetry run pytest
```

## Documentation

Update the documentation when adding or changing features. Documentation is written in Markdown and stored in the `docs/` directory.

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.
