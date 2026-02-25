# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.5.x   | Yes       |
| 1.4.x   | Yes       |
| < 1.4   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT open a public issue**
2. Email: [create a GitHub Security Advisory](https://github.com/hackingdave/nightwire/security/advisories/new)
3. Include: description, steps to reproduce, potential impact, suggested fix (if any)

You should receive a response within 48 hours. We will work with you to understand and address the issue before any public disclosure.

## Security Design Principles

### Authentication
- Only phone numbers or Signal UUIDs listed in `allowed_numbers` can interact with the bot
- Sender identifiers are partially masked in all log output
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

## Operational Security Best Practices

### Run as Dedicated User
- Create a dedicated low-privilege user (e.g., `nightwire`) for the bot
- **Never run as root** — the bot executes Claude CLI which can modify files
- Restrict the user's home directory permissions: `chmod 700 /home/nightwire`

### Firewall Rules
- The bot only needs outbound HTTPS (port 443) for the Anthropic API
- Signal bridge needs outbound to Signal servers
- Block all inbound ports except what's needed for your setup
- Example (ufw):
  ```bash
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow ssh
  ufw enable
  ```

### File System Isolation
- Set `projects_base_path` to a dedicated directory
- Use `allowed_paths` to restrict which directories Claude can access
- Optional: Enable Docker sandbox (`sandbox.enabled: true`) for task execution

### Plugin Security
- Use `plugin_allowlist` in settings.yaml to restrict which plugins load
- Review plugin code before adding to the plugins directory
- Plugins run with the same permissions as the bot process

### Resource Limits
- The bot checks system resources (memory, CPU) before spawning parallel workers
- Configure `autonomous.max_parallel` to match your system capacity (default: 3)
- Consider setting OS-level limits: `ulimit -v 4194304` (4GB virtual memory)

## Known Limitations

- Claude CLI requires `--dangerously-skip-permissions` for autonomous operation
- The verification agent uses the same permission model as the implementation agent
- Rate limiting is in-memory (resets on process restart)
