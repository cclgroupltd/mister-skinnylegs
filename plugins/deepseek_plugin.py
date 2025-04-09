import json
import re
from datetime import datetime

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from util.profile_folder_protocols import BrowserProfileProtocol


USER_DETAILS_API_URL_PATTERN = re.compile(r"chat.deepseek.*?\.[A-z]{2,3}/api/v0/users/current")
CHAT_SESSIONS_API_URL_PATTERN = re.compile(r"chat.deepseek.*?\.[A-z]{2,3}/api/v0/chat_session")
CHAT_URL_PATTERN = re.compile(r"chat.deepseek.*?\.[A-z]{2,3}/a/chat/s/[0-9a-fA-F\-]{36}$")
CHAT_MESSAGES_API_URL_PATTERN = re.compile(r'chat.deepseek.*?\.[A-z]{2,3}/api/v0/chat/history_messages\?chat_session_id=')


def get_deepseek_userinfo(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []
    
    for cache_rec in profile.iterate_cache(url=USER_DETAILS_API_URL_PATTERN):
        if cache_rec.data is None:
            log_func(f"Error: DeepSeek User Information cache file is size is zero! Skipping file.")
            continue
            
        cache_data = json.loads(cache_rec.data.decode("utf-8"))

        data = cache_data.get("data")
        email = data.get("email")
        mob_num = data.get("mobile_number")

    result = {
        "Email": email,
        "Mobile Number": mob_num or "N/A",
        "Source": "Cache",
        "Data Location": str(cache_rec.data_location)
    }

    results.append(result)

    return ArtifactResult(results)   


def get_deepseek_chat_sessions(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for cache_rec in profile.iterate_cache(url=CHAT_SESSIONS_API_URL_PATTERN):
        if cache_rec.data is None:
            log_func(f"Error: DeepSeek Chat Session information cache file is size is zero! Skipping file.")
            continue
    
        cache_data = json.loads(cache_rec.data.decode("utf-8"))

        data = cache_data.get('data')
        biz_data = data.get("biz_data")
        chat_sessions = biz_data.get("chat_sessions")

        for session in chat_sessions:
            chat_id = session.get("id")
            agent = session.get("agent")
            title = session.get("title")
            created_time = session.get("inserted_at")
            updated_time = session.get("updated_at")

            if created_time is None:
                created_timestamp = None
            else:
                created_timestamp = datetime.fromtimestamp(created_time)

            if updated_time is None:
                updated_timestamp = None
            else:
                updated_timestamp = datetime.fromtimestamp(updated_time)

            result = {
                "ID": str(chat_id),
                "Title": str(title),
                "History Timestamp": "N/A",
                "Chat Created Time": created_timestamp,
                "Chat Updated Time": updated_timestamp,
                "Orginal URL": "N/A",
                "Source": "Cache",
                "Data Location": str(cache_rec.data_location)
            }

            results.append(result)

    for history_rec in profile.iterate_history_records(url=CHAT_URL_PATTERN):
        results.append(
            {
                "ID": history_rec.url[-36:],
                "Title": history_rec.title,
                "History Timestamp": history_rec.visit_time,
                "Chat Created Time": "Unknown",
                "Chat Updated Time": "Unknown",
                "Orginal URL": history_rec.url,
                "Source": "History",
                "Data Location": history_rec.record_location 
            }
        )

    return ArtifactResult(results)   

def get_deepseek_chat_messages(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []
    
    for cache_rec in profile.iterate_cache(url=CHAT_MESSAGES_API_URL_PATTERN):
        if cache_rec.data is None:
            log_func(f"Error: DeepSeek Chat Message information cache file is size is zero! Skipping file.")
            continue
        
        cache_data = json.loads(cache_rec.data.decode("utf-8"))

        data = cache_data.get('data')
        biz_data = data.get("biz_data")
        chat_session = biz_data.get("chat_session")
        chat_messages = biz_data.get("chat_messages")

        chat_id = chat_session.get("id")
        agent = chat_session.get("agent")
        title = chat_session.get("title")
        created_time = chat_session.get("inserted_at")
        updated_time = chat_session.get("updated_at")

        if created_time is None:
            created_timestamp = None
        else:
            created_timestamp = datetime.fromtimestamp(created_time)

        if updated_time is None:
            updated_timestamp = None
        else:
            updated_timestamp = datetime.fromtimestamp(updated_time)

        for messages in chat_messages:

            message_id = messages.get("message_id")
            role = messages.get("role")
            message = messages.get("content")
            files = messages.get("files")
            sent_time = messages.get("inserted_at")

            if sent_time is None:
                sent_timestamp = None
            else:
                sent_timestamp = datetime.fromtimestamp(sent_time)

            result = {
                "ID": str(chat_id),
                "Title": str(title),
                "Chat Created Time": created_timestamp,
                "Chat Updated Time": updated_timestamp,
                "Message ID": str(message_id),
                "Message Sent Time": sent_timestamp,
                "Role": role,
                "Message": message,
                "File": files,
                "Source": "Cache",
                "Data Location": str(cache_rec.data_location)
            }
            results.append(result)

    return ArtifactResult(results) 


__artifacts__ = (
    ArtifactSpec(
        "DeepSeek",
        "DeepSeek User Information",
        "Recovers DeepSeek user information from Cache",
        "0.1",
        get_deepseek_userinfo,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "DeepSeek",
        "DeepSeek Chat Session Information",
        "Recovers DeepSeek Chat Session Information from Cache and History",
        "0.1",
        get_deepseek_chat_sessions,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "DeepSeek",
        "DeepSeek Chat Messages",
        "Recovers DeepSeek Chat Messages from Cache",
        "0.1",
        get_deepseek_chat_messages,
        ReportPresentation.table
    ),
)