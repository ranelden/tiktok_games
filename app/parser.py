import json
import re
import zipfile

VIDEO_LINK_RE = re.compile(r"tiktokv?\.com/.*/video/\d+")


def parse_export(file_stream):
    """Parse an official TikTok export (zip containing JSON files).

    Returns the list of liked videos as [{"date": str, "link": str}, ...],
    deduplicated by link.
    """
    likes = []
    with zipfile.ZipFile(file_stream) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".json"):
                continue
            with archive.open(name) as f:
                try:
                    data = json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
            likes.extend(_extract_likes(data))

    seen = set()
    unique = []
    for item in likes:
        if item["link"] not in seen:
            seen.add(item["link"])
            unique.append(item)
    return unique


def _extract_likes(node):
    # The TikTok export structure varies across versions ("Activity" >
    # "Like List" > "ItemFavoriteList", sometimes at a different depth), so we
    # search for the key recursively instead of hardcoding a fixed path.
    found = []
    if isinstance(node, dict):
        item_list = node.get("ItemFavoriteList")
        if isinstance(item_list, list):
            for entry in item_list:
                if not isinstance(entry, dict):
                    continue
                link = entry.get("Link") or entry.get("link")
                date = entry.get("Date") or entry.get("date", "")
                if link and VIDEO_LINK_RE.search(link):
                    found.append({"date": date, "link": link})
        for value in node.values():
            found.extend(_extract_likes(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_extract_likes(item))
    return found
