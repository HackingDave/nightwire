# Security Checklist for AI-Assisted / "Vibe" Coding

This document outlines common security pitfalls that can occur when rapidly building software with AI-assisted development. Before deploying code to production, review this checklist to ensure security best practices are followed.

---

# 1. Secrets & Configuration

Ensure that sensitive configuration data is handled securely.

- [ ] No hardcoded secrets, tokens, or API keys in the codebase
- [ ] Secrets are not leaking through logs, error messages, or API responses
- [ ] `.env` or other environment files are not committed to git
- [ ] API keys that should be server-side are not exposed client-side
- [ ] CORS policies are not overly permissive
- [ ] Dependencies are scanned for known vulnerabilities
- [ ] Default credentials or example configuration files have been removed
- [ ] Debug mode or development tooling is disabled in production

---

# 2. Access Control & API Security

Ensure proper authentication, authorization, and API protections are in place.

- [ ] Pages or API routes cannot be accessed without proper authentication
- [ ] Users cannot access other users’ data by modifying IDs in URLs or API requests
- [ ] Tokens are not stored insecurely on the client
- [ ] Login, signup, or password reset flows do not reveal whether an account exists
- [ ] API endpoints implement rate limiting
- [ ] Error responses do not expose internal system details
- [ ] API endpoints return only the minimum required data
- [ ] Sensitive actions (delete account, change email, etc.) require confirmation
- [ ] Admin routes are protected by authentication and authorization, not hidden URLs

---

# 3. User Input & Data Handling

All user-controlled input must be validated and sanitized.

- [ ] User input is properly sanitized before reaching database queries
- [ ] User-submitted content cannot execute code in other users' browsers (XSS)
- [ ] File uploads enforce file type and size validation
- [ ] Uploaded files are scanned and stored safely
- [ ] Payment or billing logic cannot be bypassed client-side
- [ ] Server-side validation exists for all sensitive operations

---

# 4. Dependency & Supply Chain Security

Modern applications rely heavily on third-party packages.

- [ ] All dependencies are regularly scanned (e.g., Dependabot, Snyk, etc.)
- [ ] Packages are sourced from trusted repositories
- [ ] Lockfiles (`package-lock.json`, `poetry.lock`, etc.) are committed
- [ ] Outdated or unmaintained libraries are replaced

---

# 5. Logging & Monitoring

Production systems should include appropriate security observability.

- [ ] Security-relevant events are logged (auth attempts, privilege changes)
- [ ] Logs do not contain sensitive secrets
- [ ] Alerts exist for suspicious activity
- [ ] Monitoring is enabled for API abuse and rate limit violations

---

# 6. Secure Deployment

Production deployments must enforce secure configurations.

- [ ] HTTPS is enforced
- [ ] Security headers are enabled (CSP, HSTS, X-Frame-Options, etc.)
- [ ] Infrastructure credentials are stored securely
- [ ] Production environment variables are managed securely
- [ ] Backup and recovery mechanisms are tested

---

# Notes

Rapid development tools and AI-assisted coding can accelerate development, but security review remains essential. Always perform manual validation and testing before releasing software to production.
