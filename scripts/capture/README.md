# Capture scripts

## Synapse Ask OSPF GIF

Regenerate the README GIF from the repository root:

```bash
python3 -m scripts.capture
```

Output:

```text
docs/assets/synapse-ask-real-tui-ospf.gif
```

Capture setup:

- Terminal: headless kitty in Xvfb at 1280x800, approximately 100x30 terminal cells.
- Font/theme: JetBrains Mono 14, dark Synapse-style terminal colors.
- Driver: `xdotool` types `What algorithm does OSPF use?` with deterministic human-like per-character timing.
- Recording: `ffmpeg -f x11grab` records real terminal pixels, then exports an optimized GIF with an ffmpeg palette pass and `gifsicle`.
- Timing: loaded TUI hold 2.6s, deterministic backend delay 1.2s, final answer/source hold 6s.
- Backend: deterministic local Ask webhook harness matching the live Ask response shape, used only to keep spinner timing below 3s. The captured UI is the real `Ask/ask.py` TUI and uses the normal live-webhook code path.

Validation artifacts are written under `.local-artifacts/capture/`:

```text
synapse-ask-real-tui-ospf.raw.mp4
synapse-ask-real-tui-ospf.contact.png
synapse-ask-real-tui-ospf.first.png
synapse-ask-real-tui-ospf.answer.png
synapse-ask-real-tui-ospf.final.png
```

Before committing a regenerated GIF, inspect the contact sheet and confirm:

- the first frame is the already-loaded TUI with an empty composer;
- the question is typed in the composer;
- thinking lasts less than 3 seconds;
- the final screen shows the full answer `OSPF uses Dijkstra's Shortest Path First algorithm. [1]`;
- the visible source is `Synapse-Demo/example-study-notes.md`;
- the final answer/source screen remains visible for about 6 seconds;
- there are no black frames or shell/setup commands.
