# Capture scripts

## Synapse Ask knowledge-system GIF

Regenerate the README GIF from the repository root:

```bash
python3 -m scripts.capture
```

Output:

```text
docs/assets/synapse-ask-knowledge-system.gif
```

Capture setup:

- Terminal: headless kitty in Xvfb at 1280x800, approximately 100x30 terminal cells.
- Font/theme: JetBrains Mono 14, dark Synapse-style terminal colors.
- Driver: `xdotool` types `What tools make up my knowledge system, and what are they used for?` with deterministic human-like per-character timing.
- Recording: `ffmpeg -f x11grab` records real terminal pixels, then exports an optimized GIF with an ffmpeg palette pass and `gifsicle`.
- Raw video: the portable `mpeg4` encoder is used by default; set `SYNAPSE_CAPTURE_ENCODER` to override it.
- Timing: loaded TUI hold 2.6s, deterministic backend delay 1.2s, final answer/source hold 10s.
- Backend: deterministic local Ask webhook harness matching the live Ask response shape, used only to keep spinner timing below 3s. The captured UI is the real `Ask/ask.py` TUI and uses the normal live-webhook code path.

Validation artifacts are written under `.local-artifacts/capture/`:

```text
synapse-ask-knowledge-system.raw.mp4
synapse-ask-knowledge-system.contact.png
synapse-ask-knowledge-system.first.png
synapse-ask-knowledge-system.answer.png
synapse-ask-knowledge-system.final.png
```

Before committing a regenerated GIF, inspect the contact sheet and confirm:

- the first frame is the already-loaded TUI with an empty composer;
- the question is typed in the composer;
- thinking lasts less than 3 seconds;
- the final screen shows the full knowledge-system answer with citation `[1]`;
- the visible source is `Synapse-Demo/knowledge-system-notes.md`;
- the final answer/source screen remains visible for about 10 seconds;
- there are no black frames or shell/setup commands.
