import json
import re

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from ccl_chromium_reader import ChromiumProfileFolder


def get_messages(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    # This is a basic first pass at this, designed to adhere to a tabular output, in reality a custom report
    # format is more appropriate long-term, particularly when it comes to attachments
    results = []

    for cache_rec in profile.iterate_cache(url=re.compile(r"discord.com/api/v9/channels/\d+?/messages")):
        msg_list = json.loads(cache_rec.data.decode("utf-8"))
        for msg in msg_list:
            attachments = "\n".join(
                f"ID={x["id"]}; filename='{x["filename"]}'; url='{x["url"]}'" for x in msg["attachments"])
            message_reference = None
            if msg_ref := msg.get("message_reference"):
                message_reference = f"channel={msg_ref["channel_id"]}; message={msg_ref["message_id"]}"
            results.append({
                "channel id": msg["channel_id"],
                "message id": msg["id"],
                "author id": msg["author"]["id"],
                "message type": msg["type"],
                "author username": msg["author"]["username"],
                "author global name": msg["author"]["global_name"],
                "timestamp": msg["timestamp"],
                "edited timestamp": msg["edited_timestamp"],
                "content": msg["content"],
                "attachments": attachments,
                "message reference": message_reference
            })

    results.sort(key=lambda x: (x["channel id"], x["timestamp"]))
    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Discord",
        "Discord Chat Messages",
        "Recovers Discord chat messages from the Cache",
        "0.1",
        get_messages,
        ReportPresentation.table
    ),
)