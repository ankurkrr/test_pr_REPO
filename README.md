# Test Repository for Code Governance Pipeline

This is a deliberately vulnerable and poorly-written repository designed to test the PR Review Bot and the Code Reviewer pipeline.

**DO NOT DEPLOY THIS CODE TO PRODUCTION.**

It contains examples of:
- Hardcoded secrets and passwords
- SQL Injection vulnerabilities
- OS Command Injection
- Poor cryptography (MD5)
- Bad architecture (Logic mixed with presentation)
- Code reuse violations
- Vulnerable package dependencies
- Missing docstrings and Flake8 formatting issues
- Logic bugs

## How to use:
1. Push this to a GitHub repository.
2. Set up the PR Review Bot webhook pointing to your repo.
3. Open a Pull Request modifying these files.
4. Watch the PR Review Bot catch the errors and block the PR!
