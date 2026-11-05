"""Title, description, tags, chapters, hashtags and pinned-comment text for YouTube."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .plan import Plan, chapter_lines


def build_metadata(job: dict, channel: dict, plan: Plan, out: Path) -> dict:
    m = job["metadata"]
    d = channel["description"]
    yt = channel["youtube"]
    title = m["title"].strip()
    if len(title) > 100:
        raise SystemExit(f"title is {len(title)} characters; YouTube allows 100 max")

    hashtags = list(dict.fromkeys([*m.get("hashtags", []), *d["base_hashtags"]]))[:15]
    chapters = chapter_lines(plan)
    parts = [
        m["hook"].strip(),
        d["welcome_line"].strip(),
        "Chapters\n" + "\n".join(chapters),
        m["about"].strip(),
    ]
    if m.get("keywords_paragraph"):
        parts.append(m["keywords_paragraph"].strip())
    parts += [d["footer"].strip()]
    if yt.get("contains_synthetic_media") and d.get("disclosure"):
        parts.append(d["disclosure"].strip())
    parts.append(" ".join(hashtags))
    description = "\n\n".join(parts)
    if len(description.encode("utf-8")) > 5000:
        raise SystemExit("description is over YouTube's 5000 byte limit; shorten metadata.about")

    tags, size = [], 0
    for t in [*m.get("tags", []), *d["base_tags"]]:
        t = t.strip()
        if t and t.lower() not in (x.lower() for x in tags) and size + len(t) + 1 <= 480:
            tags.append(t)
            size += len(t) + 1

    pub = job.get("publish", {})
    publish_at = pub.get("publish_at")
    if not publish_at and pub.get("publish_after_hours"):
        publish_at = (datetime.now(timezone.utc) + timedelta(hours=float(pub["publish_after_hours"]))
                      ).strftime("%Y-%m-%dT%H:%M:%SZ")

    meta = {
        "title": title,
        "description": description,
        "tags": tags,
        "category_id": m.get("category_id", yt["category_id"]),
        "language": yt["language"],
        "made_for_kids": yt["made_for_kids"],
        "contains_synthetic_media": yt["contains_synthetic_media"],
        "embeddable": yt["embeddable"],
        "public_stats_viewable": yt["public_stats_viewable"],
        "license": yt["license"],
        "notify_subscribers": yt["notify_subscribers"],
        "privacy": pub.get("privacy", "private"),
        "publish_at": publish_at,
        "playlist_id": pub.get("playlist_id") or yt.get("playlist_id"),
        "pinned_comment": m.get("pinned_comment",
                                "Welcome to indream. Where are you watching from tonight? "
                                "Tell me in the replies and I'll read them tomorrow."),
        "chapters": chapters,
        "duration_seconds": round(plan.total),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta
