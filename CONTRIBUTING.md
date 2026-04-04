# Contributing to RawToWise

Thanks for your interest in contributing! RawToWise is an early-stage project and we welcome all kinds of contributions.

## Ways to Contribute

- **Bug reports** — open an issue with reproduction steps
- **Feature requests** — describe the use case, not just the solution
- **Code** — fix a bug, improve performance, or implement a planned feature
- **Documentation** — improve README, add examples, fix typos
- **Testing** — try it on your own documents and share feedback

## Development Setup

```bash
git clone https://github.com/vericontext/rawtowise.git
cd rawtowise
pip install -e .
export ANTHROPIC_API_KEY="sk-..."
```

## Making Changes

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Test locally: `rtw init && rtw ingest <url> && rtw compile`
4. Commit with a clear message
5. Open a PR against `main`

## Code Style

- Python 3.11+
- Keep it simple — avoid premature abstractions
- No type-checking or linting CI yet, just write clean code
- All CLI output in English

## Commit Messages

Use short, descriptive messages:
```
Fix: handle URLs with special characters in ingest
Add: streaming output for query command
```

## Reporting Bugs

Include:
- `rtw version` output
- The command you ran
- Full error traceback
- OS and Python version

## Feature Requests

Before opening a feature request, check the [roadmap issues](https://github.com/vericontext/rawtowise/labels/roadmap) to see if it's already planned.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
