# Managed yt-dlp launcher

This dependency-free launcher is packaged as `tools/yt-dlp.exe`. It resolves
`../python/python.exe` from its own verified runtime location and runs:

```text
python.exe -I -B -m yt_dlp <arguments>
```

It never searches `PATH`, never invokes a shell, disables bytecode writes,
removes Python path override variables, and propagates the packaged module's exit code. The launcher exists
because a console script produced by `pip --target` embeds the build machine's
Python path and is therefore not portable or acceptable as a managed tool.
