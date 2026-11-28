"""
Runs the Roblox artifacts against the sample API responses in this directory
and validates the recovered rows. Requires no network access and no browser
profile - the sample bodies are wired into in-memory history/cache records
using the cache key URLs from manifest.json.

Usage (from the repository root):

    python3 samples/roblox/run_samples.py
"""
import datetime
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from mister_skinnylegs.plugins import roblox_plugin  # noqa: E402


class FakeLocation:
    def __init__(self, reference):
        self._reference = reference

    def __str__(self):
        return self._reference


class FakeHistoryRecord:
    def __init__(self, url, title, visit_time):
        self.url = url
        self.title = title
        self.visit_time = visit_time
        self.record_location = FakeLocation(f"History/{abs(hash(url)) % 999}")


class FakeKey:
    def __init__(self, url):
        self.url = url


class FakeMetadata:
    def __init__(self, request_time):
        self.request_time = request_time


class FakeCacheRecord:
    def __init__(self, url, request_time, data):
        self.key = FakeKey(url)
        self.data = data
        self.metadata = FakeMetadata(request_time)
        self.metadata_location = FakeLocation(f"Cache/meta/{abs(hash(url)) % 999}")
        self.data_location = FakeLocation(f"Cache/data/{abs(hash(url)) % 999}")


class FakeProfile:
    def __init__(self, history, cache):
        self._history = history
        self._cache = cache

    def iterate_history_records(self, url=None, **kwargs):
        for record in self._history:
            if url is None or url.search(record.url):
                yield record

    def iterate_cache(self, url=None, *, decompress=True, omit_cached_data=False, **kwargs):
        for record in self._cache:
            if url is None or url.search(record.key.url):
                yield record


def _parse_timestamp(text):
    return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))


def build_profile():
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    history, cache = [], []
    for record in manifest["records"]:
        note = record.get("note")
        if record["kind"] == "history":
            history.append(FakeHistoryRecord(record["url"], record["title"],
                                             _parse_timestamp(record["visit_time"])))
        elif record["kind"] == "cache":
            body_file = HERE / record["file"]
            # .txt bodies are kept verbatim (e.g. truncated cache entries);
            # .json bodies are re-serialised compactly
            if body_file.suffix == ".json":
                data = json.dumps(json.loads(body_file.read_text(encoding="utf-8")),
                                  ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            else:
                data = body_file.read_bytes()
            cache.append(FakeCacheRecord(record["url"],
                                         _parse_timestamp(record["request_time"]), data))
        else:
            raise ValueError(f"unknown record kind in manifest: {record['kind']!r}")
        if note:
            print(f"  + {pathlib.Path(record.get('file') or record['url']).name}: {note}")
    return FakeProfile(history, cache)


def main():
    profile = build_profile()
    logs = []
    log_func = logs.append

    def rows(artifact_func):
        return artifact_func(profile, log_func, None).result

    conversations = rows(roblox_plugin.get_user_conversations)
    messages = rows(roblox_plugin.get_conversation_messages)
    users = rows(roblox_plugin.get_chat_users)
    private_messages = rows(roblox_plugin.get_private_messages)
    profile_visits = rows(roblox_plugin.get_profile_visits)

    # ------------------------------------------------------------------ report
    def preview(row, fields):
        return " | ".join(f"{field}={row.get(field)}" for field in fields)

    print(f"\nRoblox Chat Conversations: {len(conversations)} row(s)")
    for row in conversations:
        print("   ", preview(row, ("name", "conversation type", "participants",
                                  "latest message sender", "source endpoint")))
    print(f"\nRoblox Chat Messages: {len(messages)} row(s)")
    for row in messages:
        print("   ", preview(row, ("conversation name", "sender name", "content",
                                  "visibility", "is deleted", "source endpoint")))
    print(f"\nRoblox Chat Users: {len(users)} row(s)")
    for row in users:
        print("   ", preview(row, ("combined name", "username", "conversations seen in",
                                   "possible account owner")))
    print(f"\nRoblox Private Messages: {len(private_messages)} row(s)")
    for row in private_messages:
        print("   ", preview(row, ("folder", "sender name", "subject", "links",
                                   "source endpoint")))
    print(f"\nRoblox Profile Visits: {len(profile_visits)} row(s)")
    for row in profile_visits:
        print("   ", preview(row, ("user id", "page title")))

    if logs:
        print("\nPlugin log:")
        for line in logs:
            print(f"    {line}")

    # -------------------------------------------------------------- assertions
    # Conversations: 2 platform + 1 legacy (the truncated listing is skipped)
    assert len(conversations) == 3, len(conversations)
    by_id = {row["conversation id"]: row for row in conversations}
    group = by_id[7462954591]
    assert group["name"] == "After school crew"
    assert "Ava (@AvaBlox2023) [9013552217]" in group["participants"]
    assert group["latest message sender"] == "Ava (@AvaBlox2023) [9013552217]"
    assert group["latest message content"] == "yeah 4pm, dont tell mom im on the laptop lol"
    stranger = by_id[1868243752]
    assert stranger["is default name"] is True and stranger["name"] == "MikeDude1985"
    assert stranger["latest message content"].startswith("dont tell your parents")
    legacy = by_id[5128849103]
    assert legacy["name"] == "SkrillexFan42"
    assert legacy["source endpoint"].startswith("legacy")

    # Messages: 15 unique. Sources: 4 from the listing (incl. the stranger's
    # hidden preview message), 6 from the per-conversation pages (one of which
    # is a duplicate of the listing's preview message), 3 legacy, 2 salvaged
    # from the truncated body.
    assert len(messages) == 15, len(messages)
    by_endpoint = {}
    for row in messages:
        by_endpoint.setdefault(row["source endpoint"], []).append(row)
    assert len(by_endpoint.get("get-user-conversations", [])) == 4
    assert len(by_endpoint.get("get-conversation-messages", [])) == 6
    assert len(by_endpoint.get("legacy get-messages (best effort)", [])) == 3
    salvaged = by_endpoint.get("get-user-conversations (salvaged from partial file)", [])
    assert len(salvaged) == 2
    assert all(row["conversation id"] is None for row in salvaged)
    assert {row["content"] for row in salvaged} == {"did u finish the science hw",
                                                    "no mr h is gonna kill me"}
    # hidden and deleted content survives recovery even though the web app
    # would not have shown it
    hidden = [row for row in messages if row["visibility"] == "hidden"]
    assert {row["content"] for row in hidden} == {
        "dont tell your parents about me ok? delete this chat",
        "or meet me at the park after school, i got a vape for u"}
    deleted = [row for row in messages if row["is deleted"]]
    assert [row["content"] for row in deleted] == ["sending u something special, check ur messages"]
    replied = [row for row in messages if row["message id"] == "4e7c1a2b-8f3d-4a5b-9c2d-1e0f9a8b7c6d"]
    assert replied and replied[0]["replies to"] == "c9bf9f57-9a56-4d3f-9db4-3f7e9a0d6f22"
    assert any("skipped 1 duplicate" in line for line in logs)

    # Users: the account owner participates in every recovered conversation
    assert len(users) == 4, len(users)
    owner = next(row for row in users if row["username"] == "AvaBlox2023")
    assert owner["possible account owner"] == "Yes"
    assert owner["conversations seen in"] == 3
    mike = next(row for row in users if row["username"] == "MikeDude1985")
    assert mike["display name"] == "Mike" and mike["possible account owner"] == "No"

    # Private messages: inbox system + scam message, sent message, plus the
    # single-message endpoint response which never appeared in a folder listing
    assert len(private_messages) == 4, len(private_messages)
    scam = next(row for row in private_messages if row["message id"] == 901562334)
    assert scam["folder"] == "inbox" and scam["is read"] is False
    assert scam["sender id"] == 6140998122
    assert "http://free-robux-claim.example/claim?id=901562334" in scam["links"]
    single = next(row for row in private_messages if row["source endpoint"] == "single message")
    assert single["message id"] == 901562999 and single["folder"] is None
    assert single["page number"] is None
    assert "http://free-robux-claim.example/claim?id=901562999" in single["links"]
    assert any("skipped 1 duplicate" in line for line in logs)  # chat message duplicate

    # Profile visits
    assert {row["user id"] for row in profile_visits} == {"6140998122", "4820117734"}
    assert len(profile_visits) == 2

    print("\nALL SAMPLE ASSERTIONS PASSED ✔")


if __name__ == "__main__":
    main()
