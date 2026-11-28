"""
Plugin for recovering Roblox chat ("thread") and private message artifacts
from browser Cache data.

Roblox operates two distinct messaging systems, both of which are processed:

1. Platform chat (instant-messaging style "threads"):

   * /platform-chat-api/v<version>/get-user-conversations - the signed-in
     user's conversation listing. Each conversation entry includes participant
     details (user_data), conversation metadata and the most recent message(s).
   * /platform-chat-api/v<version>/get-conversation-messages - a page of
     messages for a single conversation, identified by the conversation_id
     URL parameter.
   * The legacy web chat API (chat.roblox.com/v<version>/get-user-conversations
     and chat.roblox.com/v<version>/get-messages) is parsed on a best-effort
     basis for older captures; the exact shape of these responses is not
     evidenced in current captures, so all fields are accessed defensively.

2. Private messages (email-style inbox/sent service, distinct from chat):

   * /v1/messages on privatemessages.roblox.com - paged folder listings
     (the messageTab URL parameter identifies the folder). Each entry includes
     sender/recipient details, subject and the HTML message body.
   * /v1/messages/{id} - single message responses (same shape as a listing
     entry without the collection wrapper).

Note that Roblox marks chat messages/conversations which can no longer be
displayed in the app (e.g. because a participant deleted their account or
failed an age check) with a "visibility" of "hidden" or "invalid" rather than
removing them from the responses entirely, so content can still be recovered
from the Cache which the web app would not have shown the user.

Truncated / partially overwritten cache entries are not uncommon for the
larger conversation listing responses. Where a response body cannot be parsed
as JSON, complete message objects are salvaged from the raw bytes where
possible and flagged as salvaged in the output.

A further artifact recovers visits to Roblox user profile pages from browser
history, which can corroborate contact between users.

Message bodies are HTML; the plugin recovers a plain text version along with
any links (anchor hrefs and bare URLs in the text - the latter is useful for
surfacing scam/phishing links in user-sent messages).
"""
import datetime
import gzip
import html
import json
import re
import urllib.parse

from html.parser import HTMLParser

from mister_skinnylegs.util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from mister_skinnylegs.util.profile_folder_protocols import BrowserProfileProtocol


CONVERSATIONS_API_URL_PATTERN = re.compile(r"apis\.roblox\.com/platform-chat-api/v\d+/get-user-conversations")
CONVERSATION_MESSAGES_API_URL_PATTERN = re.compile(r"apis\.roblox\.com/platform-chat-api/v\d+/get-conversation-messages")
PRIVATE_MESSAGES_API_URL_PATTERN = re.compile(r"privatemessages\.roblox\.com/v\d+/messages")

# Legacy web chat API (pre platform-chat-api). Best-effort - see module docstring.
LEGACY_CONVERSATIONS_API_URL_PATTERN = re.compile(r"chat\.roblox\.com/v\d+/get-user-conversations")
LEGACY_MESSAGES_API_URL_PATTERN = re.compile(r"chat\.roblox\.com/v\d+/get-messages")

PROFILE_URL_PATTERN = re.compile(r"roblox\.com/users/(\d+)/profile")

BARE_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")

# Salvage pattern used to recover complete chat message objects from truncated
# or partially overwritten cache bodies (a whole-file json.loads() fails on
# those). Tailored to the platform-chat-api message shape, where "id" is a
# UUID-ish string appearing before "content" and "visibility" terminates the
# object. Salvage is best-effort: messages which were cut mid-object, or which
# deviate from this field order, will not be recovered.
SALVAGE_MESSAGE_PATTERN = re.compile(
    r'\{"id":"[0-9a-fA-F\-]{8,64}","content":.*?"visibility":"[a-z_]*"\}', re.DOTALL)

EPOCH = datetime.datetime(1970, 1, 1)


def _decode_unix_ms(ms) -> datetime.datetime:
    return EPOCH + datetime.timedelta(milliseconds=ms)


def _query_param(url: str, name: str):
    """
    Returns the first value of the named URL query parameter, or None.
    """
    try:
        values = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(name, [])
        return values[0] if values else None
    except ValueError:
        return None


def _conversation_id_from_url(url: str):
    """
    Extracts the conversation id URL parameter from a get-conversation-messages
    cache key URL. The platform chat API uses "conversation_id"; the legacy
    chat API used "conversationId".
    """
    return _query_param(url, "conversation_id") or _query_param(url, "conversationId")


def _read_cache_json(cache_rec, log_func: LogFunction, endpoint: str):
    """
    Returns (parsed_json_or_None, raw_text_or_None) for a cache record body.

    Copes with records which the host has not decompressed (gzip magic bytes),
    a UTF-8 BOM, and invalid/truncated JSON (in which case the raw text is
    returned so that complete records can be salvaged from it by the caller).
    """
    data = cache_rec.data
    if not data:
        log_func(f"Warning: Roblox {endpoint} cache record has no data (size zero?). "
                 f"Skipping: {cache_rec.data_location}")
        return None, None

    # Belt-and-braces: if the cache entry's header metadata is damaged the host
    # may not have decompressed the body (brotli content-encoding cannot be
    # detected from the data alone, but gzip can).
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError, ValueError) as e:
            log_func(f"Warning: could not decompress Roblox {endpoint} cache record ({e}). "
                     f"Skipping: {cache_rec.data_location}")
            return None, None

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        log_func(f"Warning: Roblox {endpoint} cache record contained invalid UTF-8; "
                 f"some characters were replaced: {cache_rec.data_location}")

    try:
        return json.loads(text), text
    except json.JSONDecodeError as e:
        log_func(f"Warning: could not parse Roblox {endpoint} cache record as JSON ({e}); "
                 f"will attempt salvage of complete records: {cache_rec.data_location}")
        return None, text


def _salvage_messages(text):
    """
    Yields complete message objects recovered from a truncated/corrupt
    platform-chat-api response body. Best-effort - see SALVAGE_MESSAGE_PATTERN.
    """
    if not text:
        return
    for match in SALVAGE_MESSAGE_PATTERN.finditer(text):
        try:
            message = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("created_at") is not None:
            yield message


def _format_username(user_record: dict):
    """
    Formats a user_data entry's names as "display_name (@username)", or just
    the username where no differing display name exists.
    """
    username = user_record.get("name")
    display_name = user_record.get("display_name")
    if display_name and username and display_name != username:
        return f"{display_name} (@{username})"
    return display_name or username


def _format_user(user_id, user_data: dict) -> str:
    """
    Formats a participant user id, adding the names from the conversation's
    user_data where they are available (e.g. "Some_guy (@rec3) [12345]").
    """
    user_record = user_data.get(str(user_id))
    if not isinstance(user_record, dict):
        return str(user_id)
    if username := _format_username(user_record):
        return f"{username} [{user_id}]"
    return str(user_id)


def _iter_conversations(profile: BrowserProfileProtocol, log_func: LogFunction):
    """
    Yields (cache_rec, conversation) tuples for each conversation entry found
    in cached platform get-user-conversations responses. Records which cannot
    be parsed are skipped here (the messages artifact performs its own salvage
    pass over unparseable listing bodies).
    """
    for cache_rec in profile.iterate_cache(url=CONVERSATIONS_API_URL_PATTERN):
        cache_data, _ = _read_cache_json(cache_rec, log_func, "get-user-conversations")
        if cache_data is None:
            continue
        conversations = cache_data.get("conversations") if isinstance(cache_data, dict) else None
        if not isinstance(conversations, list):
            log_func(f"Warning: unexpected structure in Roblox get-user-conversations cache record "
                     f"(no conversations list). Skipping: {cache_rec.data_location}")
            continue
        for conversation in conversations:
            if isinstance(conversation, dict):
                yield cache_rec, conversation
            else:
                log_func(f"Warning: unexpected conversation entry in Roblox get-user-conversations cache "
                         f"record. Skipping: {cache_rec.data_location}")


def _iter_legacy_conversations(profile: BrowserProfileProtocol, log_func: LogFunction):
    """
    Yields (cache_rec, conversation) tuples for each conversation entry found
    in cached legacy chat.roblox.com get-user-conversations responses (which
    are JSON arrays of conversation objects). Best-effort - see module docstring.
    """
    for cache_rec in profile.iterate_cache(url=LEGACY_CONVERSATIONS_API_URL_PATTERN):
        cache_data, _ = _read_cache_json(cache_rec, log_func, "legacy get-user-conversations")
        if not isinstance(cache_data, list):
            if cache_data is not None:
                log_func(f"Warning: unexpected structure in Roblox legacy get-user-conversations "
                         f"cache record (expected a list). Skipping: {cache_rec.data_location}")
            continue
        for conversation in cache_data:
            if isinstance(conversation, dict):
                yield cache_rec, conversation


def _build_chat_lookups(profile: BrowserProfileProtocol, log_func: LogFunction):
    """
    Builds user id -> name and conversation id -> name lookups from cached
    conversation listings (both platform and legacy), so that recovered
    messages and pages can be attributed by name and not just by id.
    """
    sender_lookup: dict[str, str] = {}
    conversation_lookup: dict[str, str] = {}

    for _, conversation in _iter_conversations(profile, log_func):
        conv_id = conversation.get("id")
        if conv_id is not None and conversation.get("name"):
            conversation_lookup.setdefault(str(conv_id), conversation["name"])
        for user_id, user_record in (conversation.get("user_data") or {}).items():
            if isinstance(user_record, dict) and (username := _format_username(user_record)):
                sender_lookup.setdefault(str(user_id), username)

    for _, conversation in _iter_legacy_conversations(profile, log_func):
        conv_id = conversation.get("id")
        if conv_id is not None and conversation.get("title"):
            conversation_lookup.setdefault(str(conv_id), conversation["title"])
        for participant in conversation.get("participants") or []:
            if not isinstance(participant, dict):
                continue
            user_record = {"name": participant.get("name"), "display_name": participant.get("displayName")}
            if participant.get("targetId") is not None and (username := _format_username(user_record)):
                sender_lookup.setdefault(str(participant["targetId"]), username)

    return sender_lookup, conversation_lookup


def _message_to_row(message: dict, conversation_id, conversation_name,
                    sender_lookup: dict[str, str], source_endpoint: str, cache_rec) -> dict:
    """
    Builds one report row from a chat message object. Field names for the
    legacy chat API are accepted in addition to the platform chat API's
    (missing fields are reported as None).
    """
    sender_user_id = message.get("sender_user_id", message.get("senderTargetId"))
    created_at = message.get("created_at") if message.get("created_at") is not None else message.get("sent")
    replies_to = message.get("replies_to")
    if isinstance(replies_to, dict):
        # the exact shape of a populated replies_to is not currently evidenced;
        # keep whatever identifier-like value we can find, else the raw JSON
        replies_to = replies_to.get("id") or replies_to.get("message_id") or json.dumps(replies_to)
    return {
        "conversation id": conversation_id,
        "conversation name": conversation_name,
        "message id": message.get("id"),
        "timestamp": created_at,
        "sender user id": sender_user_id,
        "sender name": sender_lookup.get(str(sender_user_id)) if sender_user_id is not None else None,
        "content": message.get("content"),
        "message type": message.get("type") or message.get("messageType") or message.get("senderType"),
        "moderation type": message.get("moderation_type"),
        "visibility": message.get("visibility"),
        "is deleted": message.get("is_deleted"),
        "is previewable": message.get("is_previewable"),
        "is badgeable": message.get("is_badgeable"),
        # legacy get-messages responses only
        "read": message.get("read"),
        "replies to": replies_to,
        "source endpoint": source_endpoint,
        "cache url": cache_rec.key.url,
        "data location": f"{cache_rec.data_location}",
    }


def get_user_conversations(profile: BrowserProfileProtocol, log_func: LogFunction,
                           storage: ArtifactStorage) -> ArtifactResult:
    results = []
    # The same conversation may be recovered from multiple cached listings
    # (re-fetches); identical snapshots are collapsed, but distinct snapshots
    # (e.g. different updated_at) are all reported as each is a separate
    # recovery point.
    seen_snapshots = set()

    def add_conversation(conversation: dict, source_endpoint: str, cache_rec):
        conversation_id = conversation.get("id")
        updated_at = conversation.get("updated_at")
        snapshot_key = (source_endpoint, str(conversation_id), str(updated_at))
        if snapshot_key in seen_snapshots:
            return
        seen_snapshots.add(snapshot_key)

        participants = conversation.get("participant_user_ids") or []
        user_data = conversation.get("user_data") or {}

        preview_message = conversation.get("preview_message")
        if not isinstance(preview_message, dict):
            messages = conversation.get("messages") or []
            preview_message = messages[0] if messages and isinstance(messages[0], dict) else None

        sort_index = conversation.get("sort_index")

        results.append({
            "conversation id": conversation_id,
            "conversation type": conversation.get("type"),
            "name": conversation.get("name"),
            "is default name": conversation.get("is_default_name"),
            "created by user id": conversation.get("created_by"),
            "participants": ", ".join(_format_user(p, user_data) for p in participants),
            "created at": conversation.get("created_at"),
            "updated at": updated_at,
            "last activity": _decode_unix_ms(sort_index) if isinstance(sort_index, (int, float)) else None,
            "unread message count": conversation.get("unread_message_count"),
            "moderation type": conversation.get("moderation_type"),
            "user pending status": conversation.get("user_pending_status"),
            "participant pending status": conversation.get("participant_pending_status"),
            "osa acknowledgement status": conversation.get("osa_acknowledgement_status"),
            "user opted into chat messages": conversation.get("user_opted_into_chat_messages"),
            "latest message content": preview_message.get("content") if preview_message else None,
            "latest message timestamp": preview_message.get("created_at") if preview_message else None,
            "latest message sender": _format_user(preview_message["sender_user_id"], user_data)
                if preview_message and preview_message.get("sender_user_id") is not None else None,
            "source endpoint": source_endpoint,
            "cache url": cache_rec.key.url,
            "data location": f"{cache_rec.data_location}",
        })

    for cache_rec, conversation in _iter_conversations(profile, log_func):
        add_conversation(conversation, "get-user-conversations", cache_rec)

    # Legacy chat.roblox.com listings (best-effort; platform-only fields are None)
    for cache_rec, conversation in _iter_legacy_conversations(profile, log_func):
        participant_lookup = {}
        for participant in conversation.get("participants") or []:
            if isinstance(participant, dict) and participant.get("targetId") is not None:
                participant_lookup[str(participant["targetId"])] = {
                    "name": participant.get("name"), "display_name": participant.get("displayName")}
        results.append({
            "conversation id": conversation.get("id"),
            "conversation type": conversation.get("conversationType"),
            "name": conversation.get("title"),
            "is default name": None,
            "created by user id": (conversation.get("initiator") or {}).get("targetId")
                if isinstance(conversation.get("initiator"), dict) else None,
            "participants": ", ".join(_format_user(p, participant_lookup)
                                      for p in participant_lookup),
            "created at": None,
            "updated at": conversation.get("lastUpdated"),
            "last activity": None,
            "unread message count": conversation.get("hasUnreadMessages"),
            "moderation type": None,
            "user pending status": None,
            "participant pending status": None,
            "osa acknowledgement status": None,
            "user opted into chat messages": None,
            "latest message content": None,
            "latest message timestamp": None,
            "latest message sender": None,
            "source endpoint": "legacy get-user-conversations (best effort)",
            "cache url": cache_rec.key.url,
            "data location": f"{cache_rec.data_location}",
        })

    results.sort(key=lambda r: r["last activity"] or EPOCH, reverse=True)
    return ArtifactResult(results)


def get_conversation_messages(profile: BrowserProfileProtocol, log_func: LogFunction,
                              storage: ArtifactStorage) -> ArtifactResult:
    sender_lookup, conversation_lookup = _build_chat_lookups(profile, log_func)

    results = []
    # Messages can be recovered from cached get-conversation-messages pages and
    # from messages embedded in conversation listings (including preview_message
    # where the messages array is empty), which may overlap. Duplicates (same
    # conversation and message id) are collapsed - Roblox chat messages are not
    # editable, so the first recovery is representative.
    seen_messages = set()
    duplicate_count = 0

    def add_messages(messages, conversation_id, source_endpoint: str, cache_rec):
        nonlocal duplicate_count
        for message in messages:
            if not isinstance(message, dict) or message.get("id") is None:
                log_func(f"Warning: skipping unexpected message entry in Roblox {source_endpoint} "
                         f"cache record: {cache_rec.data_location}")
                continue
            message_key = (str(conversation_id), str(message["id"]))
            if message_key in seen_messages:
                duplicate_count += 1
                continue
            seen_messages.add(message_key)
            results.append(_message_to_row(
                message, conversation_id, conversation_lookup.get(str(conversation_id)),
                sender_lookup, source_endpoint, cache_rec))

    # 1. Messages embedded in cached conversation listings, plus salvage from
    #    any listing bodies which are truncated/corrupt.
    for cache_rec in profile.iterate_cache(url=CONVERSATIONS_API_URL_PATTERN):
        cache_data, text = _read_cache_json(cache_rec, log_func, "get-user-conversations")
        if isinstance(cache_data, dict):
            for conversation in cache_data.get("conversations") or []:
                if not isinstance(conversation, dict):
                    continue
                candidates = [m for m in conversation.get("messages") or [] if isinstance(m, dict)]
                preview_message = conversation.get("preview_message")
                if isinstance(preview_message, dict):
                    candidates.append(preview_message)
                add_messages(candidates, conversation.get("id"), "get-user-conversations", cache_rec)
        elif text:
            add_messages(_salvage_messages(text), None,
                         "get-user-conversations (salvaged from partial file)", cache_rec)

    # 2. Cached get-conversation-messages pages (conversation id from the cache
    #    key URL, so it is still recovered for truncated bodies), plus salvage.
    for cache_rec in profile.iterate_cache(url=CONVERSATION_MESSAGES_API_URL_PATTERN):
        conversation_id = _conversation_id_from_url(cache_rec.key.url)
        if conversation_id is None:
            log_func(f"Warning: could not extract conversation_id from Roblox get-conversation-messages "
                     f"URL. Messages will have no conversation id: {cache_rec.key.url}")
        cache_data, text = _read_cache_json(cache_rec, log_func, "get-conversation-messages")
        if isinstance(cache_data, dict):
            add_messages(cache_data.get("messages") or [], conversation_id,
                         "get-conversation-messages", cache_rec)
        elif text:
            add_messages(_salvage_messages(text), conversation_id,
                         "get-conversation-messages (salvaged from partial file)", cache_rec)

    # 3. Legacy chat.roblox.com get-messages responses (best-effort).
    for cache_rec in profile.iterate_cache(url=LEGACY_MESSAGES_API_URL_PATTERN):
        conversation_id = _conversation_id_from_url(cache_rec.key.url)
        cache_data, _ = _read_cache_json(cache_rec, log_func, "legacy get-messages")
        if not isinstance(cache_data, list):
            if cache_data is not None:
                log_func(f"Warning: unexpected structure in Roblox legacy get-messages cache record "
                         f"(expected a list). Skipping: {cache_rec.data_location}")
            continue
        add_messages(cache_data, conversation_id, "legacy get-messages (best effort)", cache_rec)

    if duplicate_count:
        log_func(f"Note: skipped {duplicate_count} duplicate Roblox message record(s) already recovered from the Cache.")

    results.sort(key=lambda r: (str(r["conversation id"]), str(r["timestamp"]), str(r["message id"])))
    return ArtifactResult(results)


def get_chat_users(profile: BrowserProfileProtocol, log_func: LogFunction,
                   storage: ArtifactStorage) -> ArtifactResult:
    users: dict[str, dict] = {}
    all_conversation_ids: set[str] = set()

    def merge_user(user_id, user_record=None):
        key = str(user_id)
        record = users.get(key)
        if record is None:
            # prefer the canonical numeric id from the user_data record where
            # the dict key it was found under is suitable for lookups only
            canonical_id = user_id
            if isinstance(user_record, dict) and user_record.get("id") is not None:
                canonical_id = user_record["id"]
            record = {
                "user id": canonical_id,
                "username": None,
                "display name": None,
                "combined name": None,
                "is verified": None,
                "conversation ids": set(),
                "locations": set(),
            }
            users[key] = record
        if isinstance(user_record, dict):
            for field, column in (("name", "username"), ("display_name", "display name"),
                                  ("combined_name", "combined name")):
                if user_record.get(field) is not None and record[column] is None:
                    record[column] = user_record[field]
            if user_record.get("is_verified") is not None and record["is verified"] is None:
                record["is verified"] = user_record["is_verified"]
        return record

    def note_conversation(record, conversation_id, cache_rec):
        if conversation_id is not None:
            record["conversation ids"].add(str(conversation_id))
            all_conversation_ids.add(str(conversation_id))
        record["locations"].add(f"{cache_rec.data_location}")

    # Platform listings. Note that a cached fetch may not include user_data
    # (e.g. include_user_data=false), so bare participant ids are merged too.
    for cache_rec, conversation in _iter_conversations(profile, log_func):
        conversation_id = conversation.get("id")
        for user_id, user_record in (conversation.get("user_data") or {}).items():
            if isinstance(user_record, dict):
                note_conversation(merge_user(user_id, user_record), conversation_id, cache_rec)
        for participant_id in conversation.get("participant_user_ids") or []:
            note_conversation(merge_user(participant_id), conversation_id, cache_rec)

    # Legacy listings (best-effort)
    for cache_rec, conversation in _iter_legacy_conversations(profile, log_func):
        conversation_id = conversation.get("id")
        for participant in conversation.get("participants") or []:
            if isinstance(participant, dict) and participant.get("targetId") is not None:
                user_record = {"name": participant.get("name"),
                               "display_name": participant.get("displayName")}
                note_conversation(merge_user(participant["targetId"], user_record),
                                  conversation_id, cache_rec)

    results = []
    for record in users.values():
        conversation_ids = record.pop("conversation ids")
        locations = record.pop("locations")
        # Heuristic lead, not a fact: the account owner ordinarily participates
        # in every conversation recovered for their own account. Only meaningful
        # when more than one conversation was recovered.
        if len(all_conversation_ids) > 1 and conversation_ids == all_conversation_ids:
            possible_owner = "Yes"
        elif len(all_conversation_ids) > 1:
            possible_owner = "No"
        else:
            possible_owner = None
        shown = sorted(conversation_ids)
        conversation_ids_text = "; ".join(shown[:20])
        if len(shown) > 20:
            conversation_ids_text += f"; ...(+{len(shown) - 20} more)"
        results.append({
            "user id": record["user id"],
            "username": record["username"],
            "display name": record["display name"],
            "combined name": record["combined name"],
            "is verified": record["is verified"],
            "conversations seen in": len(conversation_ids),
            "conversation ids": conversation_ids_text or None,
            "possible account owner": possible_owner,
            "data location": "; ".join(sorted(locations)),
        })

    def sort_key(row):
        user_id = str(row["user id"])
        return (-row["conversations seen in"],
                0, int(user_id), "") if user_id.isdigit() else (-row["conversations seen in"], 1, 0, user_id)

    results.sort(key=sort_key)
    return ArtifactResult(results)


def get_profile_visits(profile: BrowserProfileProtocol, log_func: LogFunction,
                       storage: ArtifactStorage) -> ArtifactResult:
    results = []
    for history_rec in profile.iterate_history_records(url=PROFILE_URL_PATTERN):
        match = PROFILE_URL_PATTERN.search(history_rec.url)
        results.append({
            "user id": match.group(1) if match else None,
            "page title": history_rec.title,
            "visit time": history_rec.visit_time,
            "url": history_rec.url,
            "data location": f"{history_rec.record_location}",
        })
    results.sort(key=lambda r: str(r["visit time"]))
    return ArtifactResult(results)


class _MessageBodyParser(HTMLParser):
    """
    Extracts plain text and link hrefs from a Roblox private message HTML body.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self.links: list[str] = []

    def handle_data(self, data):
        self._chunks.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self._chunks.append("\n")
        elif tag == "a":
            for attr_name, attr_value in attrs:
                if attr_name.lower() == "href" and attr_value:
                    self.links.append(attr_value)

    @property
    def text(self) -> str:
        text = "".join(self._chunks)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" ?\n ?", "\n", text)
        return text.strip()


def _parse_message_body(body, log_func: LogFunction):
    """
    Converts a Roblox private message HTML body into (plain text, links).
    Links are anchor hrefs plus any bare URLs in the text - user-sent messages
    commonly contain bare URLs, some of which (e.g. "limited lookalike" scams)
    are of particular forensic interest.
    """
    if not body:
        return body, []
    try:
        parser = _MessageBodyParser()
        parser.feed(body)
        parser.close()
        text = parser.text
        links = list(dict.fromkeys(parser.links + BARE_URL_PATTERN.findall(text)))
        return text, links
    except Exception as e:
        log_func(f"Warning: could not fully parse a Roblox private message body as HTML ({e}); "
                 f"falling back to a basic tag strip.")
        text = re.sub(r"[ \t\r\f\v]+", " ", html.unescape(re.sub(r"<[^>]*>", " ", body))).strip()
        return text, list(dict.fromkeys(BARE_URL_PATTERN.findall(text)))


def get_private_messages(profile: BrowserProfileProtocol, log_func: LogFunction,
                         storage: ArtifactStorage) -> ArtifactResult:
    results = []
    # The same message can be recovered from multiple cached pages/fetches
    # (message ids are unique across folders for the account); duplicates are
    # collapsed and counted.
    seen_messages = set()
    duplicate_count = 0

    def add_message(message, folder, page_number, source_endpoint: str, cache_rec):
        nonlocal duplicate_count
        if not isinstance(message, dict) or message.get("id") is None:
            log_func(f"Warning: skipping unexpected message entry in Roblox {source_endpoint} "
                     f"cache record: {cache_rec.data_location}")
            return
        message_key = str(message["id"])
        if message_key in seen_messages:
            duplicate_count += 1
            return
        seen_messages.add(message_key)

        sender = message.get("sender") if isinstance(message.get("sender"), dict) else {}
        recipient = message.get("recipient") if isinstance(message.get("recipient"), dict) else {}
        body_text, links = _parse_message_body(message.get("body"), log_func)

        results.append({
            "message id": message.get("id"),
            "folder": folder,
            "page number": page_number,
            "sender id": sender.get("id"),
            "sender name": sender.get("name"),
            "sender display name": sender.get("displayName"),
            "sender verified": sender.get("hasVerifiedBadge"),
            "recipient id": recipient.get("id"),
            "recipient name": recipient.get("name"),
            "recipient display name": recipient.get("displayName"),
            "recipient verified": recipient.get("hasVerifiedBadge"),
            "subject": message.get("subject"),
            "body": body_text,
            "links": ", ".join(links) if links else None,
            "created": message.get("created"),
            "updated": message.get("updated"),
            "is read": message.get("isRead"),
            "is system message": message.get("isSystemMessage"),
            "is report abuse displayed": message.get("isReportAbuseDisplayed"),
            "source endpoint": source_endpoint,
            "cache url": cache_rec.key.url,
            "data location": f"{cache_rec.data_location}",
        })

    for cache_rec in profile.iterate_cache(url=PRIVATE_MESSAGES_API_URL_PATTERN):
        cache_data, _ = _read_cache_json(cache_rec, log_func, "privatemessages")
        if cache_data is None:
            continue
        folder = _query_param(cache_rec.key.url, "messageTab")
        page_number = _query_param(cache_rec.key.url, "pageNumber")
        if isinstance(cache_data, dict) and isinstance(cache_data.get("collection"), list):
            # paged listing (messageTab=inbox/sent/archive)
            messages = cache_data["collection"]
            source_endpoint = "messages listing"
        elif isinstance(cache_data, dict) and cache_data.get("id") is not None:
            # single message response (e.g. /v1/messages/{id})
            messages = [cache_data]
            source_endpoint = "single message"
        else:
            log_func(f"Warning: unexpected structure in Roblox privatemessages cache record "
                     f"(no collection list). Skipping: {cache_rec.data_location}")
            continue
        for message in messages:
            add_message(message, folder, page_number, source_endpoint, cache_rec)

    if duplicate_count:
        log_func(f"Note: skipped {duplicate_count} duplicate Roblox private message record(s) already recovered from the Cache.")

    results.sort(key=lambda r: (str(r["folder"]), str(r["created"]), str(r["message id"])))
    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Roblox",
        "Roblox Chat Conversations",
        "Recovers Roblox platform chat conversations (threads) from get-user-conversations "
        "responses in the Cache, plus legacy chat.roblox.com listings on a best-effort basis",
        "0.2",
        get_user_conversations,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Roblox",
        "Roblox Chat Messages",
        "Recovers Roblox platform chat messages from get-conversation-messages responses "
        "(including salvage of truncated cache entries) and conversation listings, plus "
        "legacy chat.roblox.com messages on a best-effort basis",
        "0.2",
        get_conversation_messages,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Roblox",
        "Roblox Chat Users",
        "Recovers Roblox chat participant details from chat conversation responses in the "
        "Cache, with an heuristic indication of the possible account owner",
        "0.2",
        get_chat_users,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Roblox",
        "Roblox Private Messages",
        "Recovers Roblox private messages (inbox/sent/archive) from privatemessages.roblox.com responses in the Cache",
        "0.1",
        get_private_messages,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Roblox",
        "Roblox Profile Visits",
        "Recovers visits to Roblox user profile pages from browser history",
        "0.1",
        get_profile_visits,
        ReportPresentation.table
    ),
)
