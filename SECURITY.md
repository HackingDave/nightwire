# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.4.x   | Yes       |
| 1.3.x   | Yes       |
| < 1.3   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public issue**
2. Email: [create a GitHub Security Advisory](https://github.com/hackingdave/sidechannel/security/advisories/new)
3. Include: description, steps to reproduce, potential impact, suggested fix (if any)

You should receive a response within 48 hours. We will work with you to understand and address the issue before any public disclosure.

## Security Design Principles

### Authentication
- Only phone numbers listed in `allowed_numbers` can interact with the bot
- Phone numbers are partially masked in all log output
- Per-user rate limiting prevents abuse (configurable window and max requests)

### Secrets Management
- API keys stored in `.env` file (excluded from git via `.gitignore`)
- No secrets hardcoded in source code
- Configuration files with sensitive data excluded from version control

### Code Execution Safety
- Claude CLI runs with local user permissions (no elevated privileges)
- Project path validation prevents directory traversal attacks
- Path prefix attack prevention (strict boundary checking)
- Input sanitization on all user-provided content

### Autonomous Task Verification
- Independent verification agent reviews all code changes
- Fail-closed policy: security concerns or logic errors block task completion
- Git checkpoints before task execution for safe rollback
- Quality gates with test baseline snapshots detect regressions

### Data Protection
- Signal messages are end-to-end encrypted in transit
- No message content logged by default
- User data deletion available (`/forget` command)
- SQLite databases stored locally (not transmitted)

## Known Limitations

- Claude CLI requires `--dangerously-skip-permissions` for autonomous operation
- The verification agent uses the same permission model as the implementation agent
- Rate limiting is in-memory (resets on process restart)
