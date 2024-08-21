import json
import re
from datetime import datetime

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from util.profile_folder_protocols import BrowserProfileProtocol


SEARCH_URL_PATTERN = re.compile(r"https?://.*chatgpt.*?\.[A-z]{2,3}/c/[0-9a-fA-F\-]{36}$")


def chatgpt_chat_urls(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for history_rec in profile.iterate_history_records(url=SEARCH_URL_PATTERN):
        results.append(
            {
                "Timestamp": history_rec.visit_time,
                "Title": history_rec.title,
                "Original URL": history_rec.url,
                "Source": "History",
                "Data Location": history_rec.record_location,
            }
        )

    results.sort(key=lambda x: x["Timestamp"])
    return ArtifactResult(results)


def get_chatgpt_chatinfo(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    url_pattern = re.compile(r"chatgpt.*?\.[A-z]{2,3}/backend-api/conversations\?offset")
    
    for cache_rec in profile.iterate_cache(url=url_pattern):
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        items = cache_data.get("items", {})
        for chat_item in items:
            id = chat_item.get("id")
            title = chat_item.get("title") or None
            create_time = chat_item.get("create_time")
            update_time = chat_item.get("update_time")

            result = { 
                "ID": str(id),
                "Title": str(title),
                "Created Time": create_time,
                "Updated Time": update_time,
                "Source": "Cache",
                "Data Location": str(cache_rec.data_location)
            }

            results.append(result)

    return ArtifactResult(results)


def get_chatgpt_userinfo(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    url_pattern = re.compile(r"chatgpt.*?\.[A-z]{2,3}/backend-api/me")

    for cache_rec in profile.iterate_cache(url=url_pattern):
        cache_data = json.loads(cache_rec.data.decode("utf-8"))

        name = cache_data.get("name")
        email = cache_data.get("email")
        phone_number = cache_data.get("phone_number")
        created = cache_data.get("created")
        standard_timestamp = datetime.fromtimestamp(created)

    
        result = {
            "Created": str(standard_timestamp),
            "Name": name,
            "Email": email,
            "Phone Number": str(phone_number),
            "Source": "Cache",
            "Data Location": str(cache_rec.data_location)
            }

        results.append(result)

    return ArtifactResult(results)   


__artifacts__ = (
    ArtifactSpec(
        "ChatGPT",
        "ChatGPT Chat URLs and Titles",
        "Recovers ChatGPT chat titles and URLs from History",
        "0.1",
        chatgpt_chat_urls,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "ChatGPT",
        "ChatGPT Chat Information",
        "Recovers ChatGPT chat titles, creation and update times from Cache",
        "0.1",
        get_chatgpt_chatinfo,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "ChatGPT",
        "ChatGPT User Information",
        "Recovers ChatGPT user information from Cache",
        "0.1",
        get_chatgpt_userinfo,
        ReportPresentation.table
    ),
)
