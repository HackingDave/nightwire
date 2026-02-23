# BluOS Music Plugin

Multi-room speaker control for BluOS-compatible devices (Bluesound, NAD, etc.).

## Configuration

Add to `config/settings.yaml`:

```yaml
plugins:
  bluos_music:
    enabled: true
    players:
      main_floor:
        name: "Main Floor"
        ip: "10.0.0.1"
      bedroom:
        name: "Bedroom"
        ip: "10.0.0.2"
    groups:
      inside: [main_floor, bedroom]
      all: [main_floor, bedroom]
```

## Commands

- `/music <command>` -- Direct music control
- Natural language: "play jazz in the bedroom", "pause", "volume 50"

## Supported Actions

- play, pause, stop, skip/next, previous
- volume (0-100), mute, unmute
- what's playing / now playing
- shuffle, repeat
