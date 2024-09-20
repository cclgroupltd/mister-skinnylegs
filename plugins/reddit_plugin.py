import datetime
import itertools
import json
import mimetypes
import pathlib
import re
import typing
import urllib.parse

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from util.profile_folder_protocols import BrowserProfileProtocol

# This appears to be an implementation of the Matrix chat platform. With some work we could probably abstract this
#  to work with Matrix in a generic fashion? Not sure where else we see it at the moment though.

# API endpoint documentation:
# https://playground.matrix.org/#get-/_matrix/client/v3/rooms/-roomId-/messages
# https://playground.matrix.org/#get-/_matrix/client/v3/sync
REDDIT_MATRIX_ROOMS_PATTERN = re.compile(r"matrix\.redditspace\.com/_matrix/client/v3/rooms")
REDDIT_MATRIX_SYNC_PATTERN = re.compile(r"matrix\.redditspace\.com/_matrix/client/v3/sync")
REDDIT_MATRIX_THUMBNAIL_PATTERN = re.compile(r"matrix\.redditspace\.com/_matrix/media/v3/thumbnail")
REDDIT_MATRIX_DOWNLOAD_PATTERN = re.compile(r"matrix\.redditspace\.com/_matrix/media/v3/download")

# Set this to True if you want to fall over on unexpected data for testing and debugging, otherwise
#  it's warnings in the log.
RAISE_ON_UNEXPECTED_DATA = False

EPOCH = datetime.datetime(1970, 1, 1)

# Thumbnails are mostly (all?) webp, and the mimetypes module doesn't recognise that out of the box.
mimetypes.add_type("image/webp", ".webp")


def decode_unix_ms(ms):
    return EPOCH + datetime.timedelta(milliseconds=ms)


def process_message(event: dict, result: dict, log_func: LogFunction):
    # TODO: Reactions? (unsigned.m.relations.m.annotation)
    result["type"] = "message"

    if not event["content"]:
        # no content, check for redaction
        if "redacted_because" in event["unsigned"]:
            result["was deleted"] = True
            result["deleted by user id"] = event["unsigned"]["redacted_because"]["sender"]
            result["deleted by event id"] = event["unsigned"]["redacted_because"].get("event_id")
    else:
        match event["content"].get("msgtype"):
            case "m.text":
                result["text"] = event["content"]["body"]
            case "m.image":
                result["image reference"] = event["content"]["url"]
            case None:
                result["_WARNING_ UNPARSED DATA"] = json.dumps(event)
                log_func(f"WARNING: Missing msgtype: {json.dumps(event)}")
            case _:
                if RAISE_ON_UNEXPECTED_DATA:
                    log_func(json.dumps(event))
                    raise NotImplementedError(f"Unexpected msgtype: {event["content"]["msgtype"]}")
                else:
                    result["_WARNING_ UNPARSED DATA"] = json.dumps(event)
                    log_func(f"WARNING: Unexpected msgtype: {event["content"]["msgtype"]}")

        if relates_to := event["content"].get("m.relates_to"):
            match relates_to["rel_type"]:
                case "m.thread":
                    result["is in thread"] = True
                    result["thread parent event"] = relates_to["event_id"]
                    if "m.in_reply_to" in relates_to:
                        result["in reply to"] = relates_to["m.in_reply_to"]["event_id"]
                case _:
                    if RAISE_ON_UNEXPECTED_DATA:
                        log_func(json.dumps(event))
                        raise NotImplementedError(f"Unexpected rel_type: {relates_to["rel_type"]}")
                    else:
                        result["_WARNING_ UNPARSED DATA"] = json.dumps(event)
                        log_func(f"WARNING: Unexpected rel_type: {relates_to["rel_type"]}")


def process_event(
        event: dict, messages_raw: list,
        display_name_lookup: dict[str, str], data_location: str,
        log_func: LogFunction) -> typing.NoReturn:
    # Might not always need the result, but we'll grab it here
    result = {
        "timestamp utc": decode_unix_ms(event["origin_server_ts"]),
        "data location": data_location,
        "room id": event.get("room_id"),
        "event id": event["event_id"],
        "type": None,  # add this to be filled later, so it always appears before other stuff
        "sender id": event["sender"],
        "sender display name": None,  # add this now to be updated later once collated
        "text": None  # add this to be filled later, so it always appears before other stuff
    }
    match event["type"]:
        case "m.room.message":
            process_message(event, result, log_func)
            messages_raw.append(result)
        case "m.sticker":
            result["type"] = "sticker"
            result["sticker name"] = event["content"]["body"]
            result["sticker reference"] = event["content"]["url"]
            messages_raw.append(result)
        case "m.room.redaction":
            result["type"] = "message deletion"
            result["deleted event id"] = event["redacts"]
            messages_raw.append(result)
        case "m.room.create":
            result["type"] = f"direct chat room created" if event["unsigned"]["is_direct"] else "chat room created"
            messages_raw.append(result)
        case "m.room.member":
            result["type"] = f"chat member {event["content"]["membership"]}"
            result["member id"] = event["state_key"]
            result["display name"] = event["content"]["displayname"]
            messages_raw.append(result)

            # add the display name to the lookup if we can (we need both of these fields to do it safely)
            if "room_id" in event and "state_key" in event:
                # display_name_key = (event["room_id"], event["state_key"])
                display_name_key = event["state_key"]
                if display_name_key in display_name_lookup:
                    if display_name_lookup[display_name_key] != event["content"]["displayname"]:
                        raise NotImplementedError(
                            "Display name for a single user changes, this is not currently supported")
                else:
                    display_name_lookup[display_name_key] = event["content"]["displayname"]
        case "m.room.power_levels":
            pass  # I can't see where this could be useful
        case "m.room.join_rules":
            result["type"] = f"join rules set: {event["content"]["join_rule"]}"
            messages_raw.append(result)
        case "com.reddit.chat.type":
            result["type"] = f"chat type set: {event["content"]["type"]}"
            messages_raw.append(result)
        case "m.room.history_visibility":
            result["type"] = f"history visibility set: {event["content"]["history_visibility"]}"
            messages_raw.append(result)
        case _:
            if RAISE_ON_UNEXPECTED_DATA:
                raise NotImplementedError(f"Unexpected event type: {event["type"]}")
            else:
                result["_WARNING_ UNPARSED DATA"] = json.dumps(event)
                messages_raw.append(result)
                log_func(f"WARNING: Unexpected event type: {event["type"]}")


def process_room_endpoint(url: str, obj: dict, messages_raw: list,
                          display_name_lookup: dict[str, str], data_location: str,
                          log_func: LogFunction) -> typing.NoReturn:
    if "/event" in url:
        # a single event rather than a list, so put the whole thing in a list
        if "error" in obj:
            records = []
        else:
            records = [obj]
    elif "/messages" in url or "/members" in url:
        if "error" in obj:
            records = []
        else:
            records = itertools.chain(
                obj["chunk"], obj.get("state", []), *obj.get("updates", {}).values())
    else:
        if RAISE_ON_UNEXPECTED_DATA:
            raise NotImplementedError(f"Unexpected URL format: {url}")
        else:
            log_func(f"WARNING: Unexpected URL format: {url}")
            records = []

    for event in records:
        process_event(event, messages_raw, display_name_lookup, data_location, log_func)


def get_messages(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    # we have to collate everything together before we can assign display names, images, etc.
    messages_raw = []
    # display_name_lookup: dict[tuple[str, str], str] = {}  # (room, user id) : display name
    display_name_lookup: dict[str, str] = {}  # user id: display name
    media_lookup = {}
    for i, record in enumerate(profile.iterate_cache(
            url=lambda x: any(y.search(x) is not None for y in (
                    REDDIT_MATRIX_SYNC_PATTERN,
                    REDDIT_MATRIX_ROOMS_PATTERN,
                    REDDIT_MATRIX_THUMBNAIL_PATTERN,
                    REDDIT_MATRIX_DOWNLOAD_PATTERN)))):

        if REDDIT_MATRIX_ROOMS_PATTERN.search(record.key.url):
            obj = json.loads(record.data.decode("utf-8"))
            process_room_endpoint(record.key.url, obj, messages_raw, display_name_lookup, str(record.data_location), log_func)
        elif REDDIT_MATRIX_SYNC_PATTERN.search(record.key.url) and record.data:
            try:
                data = record.data.decode("utf-8")
            except UnicodeDecodeError:
                log_func(f"WARNING: Couldn't read record with cache key '{record.key}'; skipping this record")
                continue
            # this endpoint returns data which goes <length in hex of record>\n<record of that length (json)>\n
            # I don't really care about the length, so it's just a case of taking every other line
            for line in data.splitlines(keepends=False)[1::2]:
                obj = json.loads(line)
                room_data = obj["rooms"]["join"]
                for room in room_data.values():
                    # in testing so far, ephemeral
                    records = itertools.chain(
                        room["state"]["events"],
                        room["timeline"]["events"],
                        *room["timeline"]["updates"].values(),
                        # room["ephemeral"]["events"],  # mostly x is typing and read receipts, formatted differently
                        room["account_data"]["events"]
                    )
                    for event in records:
                        process_event(event, messages_raw, display_name_lookup, str(record.data_location), log_func)
        elif REDDIT_MATRIX_THUMBNAIL_PATTERN.search(record.key.url) or REDDIT_MATRIX_DOWNLOAD_PATTERN.search(record.key.url):
            # thumbnails/images are not actually the record, but the ID is in the path and the actual URL is in
            #  the location header field. We use a list in case there are different resolutions - we want them all.
            location = record.metadata.get_attribute("location")
            if location:
                thumb_path = urllib.parse.urlparse(record.key.url).path
                thumb_id = pathlib.PurePosixPath(thumb_path).parts[-1]
                media_lookup.setdefault(thumb_id, set())
                media_lookup[thumb_id].add(location[0])

    # Get data from indexed db - functionally the ame structure as data held in the Sync records in the cache
    for rec in profile.iter_indexeddb_records(
            host_id=re.compile(r"chat\.reddit\.com"),
            database_name="matrix-js-sdk:reddit-chat-sync",
            object_store_name="sync"):
        for join_obj in rec.value["roomsData"]["join"].values():
            events = itertools.chain(join_obj["state"]["events"], join_obj["timeline"]["events"])
            for event in events:
                process_event(event, messages_raw, display_name_lookup, rec.record_location, log_func)

    # Go and get media files
    # a reverse lookup would be faster, but needs a one to one with content-to-id but the same resource can
    #  be attributed to multiple ids, annoyingly.
    file_exports: dict[str: int] = {}  # id to a count to do file naming
    for record in profile.iterate_cache():
        key_hits = []
        if not record.data:
            continue
        for media_id, vals in media_lookup.items():
            if record.key.url in vals:
                key_hits.append(media_id)
                vals.remove(record.key.url)
        for media_id in key_hits:
            file_exports.setdefault(media_id, 0)
            file_exports[media_id] += 1
            out_extension = ""
            if record.metadata and (mime := record.metadata.get_attribute("content-type")):
                out_extension = mimetypes.guess_extension(mime[0]) or ""
            with storage.get_binary_stream(f"{media_id}_{file_exports[media_id]}{out_extension}") as o:
                o.write(record.data)

    # Build a lookup and try and fix up records without a room
    event_to_room_id = {m["event id"]: m["room id"] for m in messages_raw if m["room id"] is not None}
    for m in messages_raw:
        if m["room id"] is None and m["event id"] in event_to_room_id:
            m["room id"] = event_to_room_id[m["event id"]]

    # Insert display names if we've found them
    for message in messages_raw:
        # display_name_key = (message["room id"], message["sender id"])
        display_name_key = message["sender id"]
        message["sender display name"] = display_name_lookup.get(display_name_key)

    # a little hacky, but effective method to deduplicate messages. This works as the dict isn't nested in here;
    #  don't do this for nested dicts - it won't work!
    messages_deduped = sorted(
        {tuple((k, v) for (k, v) in sorted(msg.items()) if k != "data location"): msg for msg in messages_raw}.values(),
        key=lambda x: x["timestamp utc"])

    return ArtifactResult(messages_deduped)


__artifacts__ = (
    ArtifactSpec(
        "Reddit",
        "Reddit Chat Messages",
        "Recovers Reddit chat messages from the Cache and IndexedDB",
        "0.2",
        get_messages,
        ReportPresentation.table
    ),
)
