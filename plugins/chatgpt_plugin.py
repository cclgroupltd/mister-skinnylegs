import json
import re
from datetime import datetime

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from util.profile_folder_protocols import BrowserProfileProtocol


CONVERSATION_API_URL_PATTERN = re.compile(r"chatgpt.*?\.[A-z]{2,3}/backend-api/conversations\?offset")
CONVERSATION_URL_PATTERN = re.compile(r"https?://.*chatgpt.*?\.[A-z]{2,3}/c/[0-9a-fA-F\-]{36}$")
USER_DETAILS_API_URL_PATTERN = re.compile(r"chatgpt.*?\.[A-z]{2,3}/backend-api/me")


def get_chatgpt_chatinfo(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []
    
    for cache_rec in profile.iterate_cache(url=CONVERSATION_API_URL_PATTERN):
        if cache_rec.data is None:
            log_func(f"Error: ChatGPT chat information cache file is size is zero! Skipping file.")
            continue
            
        cache_data = json.loads(cache_rec.data.decode("utf-8"))
    
        items = cache_data.get("items", {})
        for chat_item in items:
            chat_id = chat_item.get("id")
            title = chat_item.get("title") or None
            create_time = chat_item.get("create_time")
            update_time = chat_item.get("update_time")

            result = { 
                "ID": str(chat_id),
                "Title": str(title),
                "History Timestamp": "N/A",
                "Chat Created Time": create_time,
                "Chat Updated Time": update_time,
                "Original URL": "N/A",
                "Source": "Cache",
                "Data Location": str(cache_rec.data_location)
            }

            results.append(result)

    for history_rec in profile.iterate_history_records(url=CONVERSATION_URL_PATTERN):
        results.append(
            {
                "ID": history_rec.url[-36:],
                "Title": history_rec.title,
                "History Timestamp": history_rec.visit_time,
                "Chat Created Time": "Unknown",
                "Chat Updated Time": "Unknown",
                "Original URL": history_rec.url,
                "Source": "History",
                "Data Location": history_rec.record_location,
            }
        )

    return ArtifactResult(results)


def get_chatgpt_userinfo(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for cache_rec in profile.iterate_cache(url=USER_DETAILS_API_URL_PATTERN):
        if cache_rec.data is None:
            log_func(f"Error: ChatGPT user information cache file is size is zero! Skipping file.")
            continue
            
        cache_data = json.loads(cache_rec.data.decode("utf-8"))

        name = cache_data.get("name")
        email = cache_data.get("email")
        phone_number = cache_data.get("phone_number")
        created = cache_data.get("created")
        
        if created is None:
            standard_timestamp = None
        else:
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
        "ChatGPT Chat Information",
        "Recovers ChatGPT chat information from History and Cache",
        "0.2",
        get_chatgpt_chatinfo,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "ChatGPT",
        "ChatGPT User Information",
        "Recovers ChatGPT user information from Cache",
        "0.2",
        get_chatgpt_userinfo,
        ReportPresentation.table
    ),
)
