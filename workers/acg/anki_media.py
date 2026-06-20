from __future__ import annotations

import html


def anki_video_html(
    webm_filename: str,
    mp4_filename: str = "",
    poster_filename: str = "",
    *,
    controls: bool = True,
    muted: bool = False,
) -> str:
    if not webm_filename and not mp4_filename:
        return ""
    poster_attr = ""
    poster_preload = ""
    if poster_filename:
        safe_poster = html.escape(poster_filename, quote=True)
        poster_attr = f' poster="{safe_poster}"'
        poster_preload = f'<img src="{safe_poster}" alt="" style="display:none">'
    sources: list[str] = []
    if webm_filename:
        safe_webm = html.escape(webm_filename, quote=True)
        sources.append(f'<source src="{safe_webm}" type="video/webm">')
    if mp4_filename:
        safe_mp4 = html.escape(mp4_filename, quote=True)
        sources.append(f'<source src="{safe_mp4}" type="video/mp4">')
    fallback = '<span class="anki-video-fallback" aria-hidden="true" style="display:none"></span>'
    attrs = ["loop", "playsinline", 'preload="metadata"']
    if controls:
        attrs.append("controls")
    if muted:
        attrs.append("muted")
    return f'{poster_preload}<video {" ".join(attrs)}{poster_attr}>{"".join(sources)}{fallback}</video>'


def anki_audio_html(filename: str, *, controls: bool = True, role: str = "") -> str:
    if not filename:
        return ""
    safe_name = html.escape(filename, quote=True)
    controls_attr = " controls" if controls else ""
    role_attr = f' data-audio-role="{html.escape(role, quote=True)}"' if role else ""
    return f'<audio{controls_attr} preload="metadata"{role_attr}><source src="{safe_name}" type="audio/mpeg"></audio>'
