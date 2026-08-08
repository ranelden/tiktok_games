import logging
import re
import urllib.error
import urllib.parse
import urllib.request

VIDEO_ID_RE = re.compile(r"video/(\d+)")
TIMEOUT_SECONDS = 4
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

logger = logging.getLogger(__name__)


def is_available(link):
    """Best-effort check that a TikTok video is still up, via TikTok's public
    oEmbed endpoint (returns 200 with metadata for a live video, 400 for a
    deleted/private/invalid one). Fails open (assumes available) on network
    errors or timeouts, so a transient connectivity issue never wrongly empties
    the whole video pool.
    """
    match = VIDEO_ID_RE.search(link)
    if not match:
        return True

    # oEmbed needs a canonical tiktok.com URL, not the tiktokv.com/share/...
    # links stored from the export — an empty username segment works fine.
    check_url = f"https://www.tiktok.com/@/video/{match.group(1)}"
    oembed_url = "https://www.tiktok.com/oembed?url=" + urllib.parse.quote(check_url, safe="")
    req = urllib.request.Request(oembed_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False
    except (urllib.error.URLError, OSError):
        logger.warning("Availability check failed for %s, assuming available", link)
        return True
