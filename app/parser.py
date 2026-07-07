import json
import re
import zipfile

VIDEO_LINK_RE = re.compile(r"tiktokv?\.com/.*/video/\d+")


def parse_export(file_stream):
    """Parse un export officiel TikTok (zip contenant des JSON).

    Retourne la liste des vidéos likées sous la forme
    [{"date": str, "link": str}, ...], dédupliquée par lien.
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
    # La structure de l'export TikTok varie selon les versions ("Activity" >
    # "Like List" > "ItemFavoriteList", parfois à un autre niveau), donc on
    # cherche récursivement la clé plutôt que de fixer un chemin.
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
