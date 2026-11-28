# Roblox API samples

Synthetic sample **Roblox API response bodies** covering every Roblox endpoint
the plugin parses, plus a runner script which feeds them through the Roblox
artifacts without needing a real browser capture:

```
python3 samples/roblox/run_samples.py
```

The runner wires each body into an in-memory cache record under the cache key
URL the browser would have used (that URL carries the parameters the artifacts
read, e.g. `conversation_id`, `messageTab`, `pageNumber`), runs all five
Roblox artifacts and asserts on the recovered rows.

> These samples are **synthetic demonstrations** written to the documented URL
> schemas the plugin parses - they are not captured evidence. Any resemblance
> to real accounts is coincidental; external links use reserved domains
> (`.example`).

## Why synthetic samples?

The plugin's decoders were originally built and validated against real
captures held outside this repository (which cannot be redistributed). These
samples reproduce the same response shapes so that:

- the parsing behaviour (including edge cases) can be demonstrated end-to-end
  without real evidence, and
- future changes to the plugin can be checked against a stable corpus.

## What the corpus exercises

| Behaviour | Sample |
|---|---|
| Conversation listing with embedded messages + preview message, group naming | `get-user-conversations_page0.json` |
| One-to-one conversation with default name and preview only | `get-user-conversations_page0.json` |
| Truncated / partially overwritten cache body → message salvage | `get-user-conversations_page1.truncated.txt` |
| Per-conversation message pages, conversation id from the cache key URL | `get-conversation-messages_conv*.json` |
| Moderated content (`visibility: hidden`) and deleted messages surviving recovery | `get-conversation-messages_conv1868243752.json` |
| Message replies (`replies_to`) | `get-user-conversations_page0.json` |
| Duplicate collapsing across listing/page endpoints | listing vs `get-conversation-messages_conv1868243752.json` |
| Legacy web chat (best-effort camelCase shapes) | `legacy_chat_*.json` |
| Private messages: paged folders, system messages, HTML body → plain text + link extraction (anchor hrefs and bare scam URLs) | `privatemessages_inbox_page0.json`, `privatemessages_sent_page0.json` |
| Single-message endpoint (`/v1/messages/{id}`) with no folder context | `privatemessages_message_901562999.json` |
| Profile page visits from browser history | manifest `history` records |

## Files

| File | Endpoint | Consumed by |
|---|---|---|
| `manifest.json` | - | maps each body to its cache key URL / history record |
| `bodies/get-user-conversations_page0.json` | `apis.roblox.com/platform-chat-api/v1/get-user-conversations` | Chat Conversations, Chat Messages, Chat Users |
| `bodies/get-user-conversations_page1.truncated.txt` | same (corrupt body) | Chat Messages (salvage) |
| `bodies/get-conversation-messages_conv7462954591.json` | `apis.roblox.com/platform-chat-api/v1/get-conversation-messages?conversation_id=...` | Chat Messages |
| `bodies/get-conversation-messages_conv1868243752.json` | same | Chat Messages |
| `bodies/legacy_chat_get-user-conversations.json` | `chat.roblox.com/v1/get-user-conversations` (legacy) | Chat Conversations (best effort), Chat Users |
| `bodies/legacy_chat_get-messages_conv5128849103.json` | `chat.roblox.com/v1/get-messages?conversationId=...` (legacy) | Chat Messages (best effort) |
| `bodies/privatemessages_inbox_page0.json` | `privatemessages.roblox.com/v1/messages?messageTab=inbox...` | Private Messages |
| `bodies/privatemessages_sent_page0.json` | same, `messageTab=sent` | Private Messages |
| `bodies/privatemessages_message_901562999.json` | `privatemessages.roblox.com/v1/messages/{id}` | Private Messages |
| `run_samples.py` | - | runner / validation |

## Expected output

The runner recovers 3 conversations, 15 unique chat messages (2 of them
salvaged from the truncated body), 4 chat users (with the account-owner
heuristic flagging the participant present in every conversation), 4 private
messages (including the links extracted from the scam message body) and 2
profile visits - and asserts all of it before reporting success.
