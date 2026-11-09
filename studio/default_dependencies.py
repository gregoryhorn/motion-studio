"""Shared default-tool dependency pack metadata; no installer side effects.

Release assembly may include these records verbatim. Presence/discovery is not a
platform qualification, pin, installation consent or successful network exercise.
"""
DEFAULT_TOOL_PACKS: list[dict] = [dict(id='public-source-acquisition', required=True,
    platforms=['linux'], operations=['asset.acquire@1'], compatibility=None,
    dependencies=[dict(kind='executable', identifier=name, constraint=None,
        source=source, sha256=None, size=None, verification='binding-discovery',
        delivery='existing', notices=[notice]) for name, source, notice in (
            ('yt-dlp', 'https://github.com/yt-dlp/yt-dlp',
             'Operator-managed executable. V1 requires no-plugin-dirs, no-remote-components and no-js-runtimes; missing/old CLI fails explicitly. No cookies or authentication.'),
            ('prlimit', 'https://github.com/util-linux/util-linux',
             'Linux util-linux per-file hard resource bound. Existing host dependency, not installed automatically.'),
            ('ffmpeg', 'https://ffmpeg.org/about.html',
             'Existing decoder; acquisition does not install or replace shared media tools.'),
            ('ffprobe', 'https://ffmpeg.org/ffprobe.html',
             'Existing probe; passive discovery is not production qualification.'),
        )])]
