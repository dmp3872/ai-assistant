# Run the Video Clipper on your Mac (no Terminal)

1. In Finder, open this `mac` folder inside the project.
2. **Double-click `Clipper.command`.**
   - First time only: macOS may say it's from an unidentified developer. Right-click
     `Clipper.command` → **Open** → **Open**. (You only do this once.)
3. A Terminal window opens and sets things up the first time (Python packages + ffmpeg —
   a few minutes). After that it's instant.
4. Your browser opens the **Video Clipper** at `http://localhost:4318`.
5. **Drag your video onto the page.** It clips it into natural 5–7 minute segments; play or
   download each clip. Files are saved to `clipper_output/` inside the project.

To stop it, close the Terminal window it opened.

Everything runs on your Mac — the video never leaves your computer.
