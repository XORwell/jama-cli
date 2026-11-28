# Contributing to Jama CLI

We love your input! We want to make contributing to Jama CLI as easy and transparent as possible, whether it's:

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
   poetry run pre-commit install --hook-type pre-commit --hook-type pre-push
   ```

### Code Quality

Run the same checks as CI from the repository root:

```bash
poetry run ruff check .
poetry run black --check .
poetry run isort --check-only .
poetry run mypy jama_cli jama_mcp_server
```

## Testing

Please write tests for any new features or bug fixes. Run the default unit test suite from the repository root. It uses test doubles and requires no live Jama instance. CI runs this suite on Python 3.10, 3.11, and 3.12.

```bash
poetry run pytest
```

To run a single unit test during development, pass its pytest node ID to `poetry run pytest`. Tests that require a live Jama instance are opt-in and can require credentials and test data.

## Documentation

Update the documentation when adding or changing features. Update the relevant usage examples in `README.md` or `EXAMPLES.md` when command behavior changes.

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.
