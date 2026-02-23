# Daily Verse Plugin

Delivers a daily Bible verse to configured recipients at a scheduled time.

## Configuration

Add to `config/settings.yaml`:

```yaml
plugins:
  daily_verse:
    enabled: true
    hour: 8        # Hour to send (24h format, default: 8)
    minute: 0      # Minute to send (default: 0)
    recipients:    # Phone numbers (default: all allowed_numbers)
      - "+1XXXXXXXXXX"
```

## Environment Variables

Requires one of:
- `OPENAI_API_KEY` — for OpenAI-powered verse generation
- `GROK_API_KEY` — for Grok-powered verse generation

## Commands

- `/verse` — Get a Bible verse on demand
