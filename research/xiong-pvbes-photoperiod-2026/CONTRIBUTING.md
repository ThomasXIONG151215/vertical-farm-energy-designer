# Contributing to OpenCROPS

Thank you for your interest in contributing to OpenCROPS! This document provides guidelines and instructions for contributing.

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
By participating, you are expected to uphold this code.

## Getting Started

### Prerequisites

- Python 3.10 or higher
- Git

### Development Environment Setup

1. **Fork the repository** on GitHub

2. **Clone your fork:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/OpenCROPS.git
   cd OpenCROPS
   ```

3. **Add upstream remote:**
   ```bash
   git remote add upstream https://github.com/ORIGINAL_OWNER/OpenCROPS.git
   ```

4. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/macOS
   venv\Scripts\activate     # Windows
   ```

5. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install pytest black flake8
   ```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 2. Make Your Changes

- Write clean, well-documented code
- Follow the existing code style
- Add comments for complex logic
- Update documentation as needed

### 3. Test Your Changes

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=. --cov-report=html

# Run specific test file
pytest tests/test_optimizer.py -v
```

### 4. Format Your Code

```bash
# Format code with black
black src/

# Check formatting without making changes
black --check src/
```

### 5. Lint Your Code

```bash
flake8 src/ --max-line-length=120 --ignore=E501,W503
```

### 6. Commit Your Changes

```bash
git add .
git commit -m "feat: add new feature"
git commit -m "fix: resolve issue with optimizer"
```

**Commit message format:**
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

### 7. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

## Project Structure

```
OpenCROPS/
├── src/                  # Main source code
│   ├── __init__.py
│   ├── system.py         # Energy system simulation
│   ├── optimizer.py      # Optimization algorithms
│   ├── visualization.py  # Visualization utilities
│   ├── utils.py          # Utility functions
│   ├── calibrator.py     # Calibration module
│   └── battery.py        # Battery modeling
├── tests/                # Test files (to be added)
├── weather/              # Weather data files
├── idfs/                 # EnergyPlus IDF files
├── docs/                 # Documentation
└── main.py               # Entry point
```

## Writing Tests

- Place tests in the `tests/` directory
- Name test files as `test_<module_name>.py`
- Use descriptive test function names
- Include docstrings for test functions

Example:
```python
def test_optimizer_convergence():
    """Test that optimizer converges to acceptable solution."""
    result = optimizer.optimize(...)
    assert result.success is True
    assert result.fun < 1e-6
```

## Reporting Issues

- Use the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md)
- Use the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md)
- Search existing issues before creating new ones
- Include relevant details (Python version, OS, error messages)

## Questions?

Feel free to:
- Open an issue for questions
- Participate in discussions
- Reach out to the maintainers

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
