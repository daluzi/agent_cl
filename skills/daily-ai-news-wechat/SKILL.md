---
name: daily-ai-news-wechat
description: Daily fetch AI-related content (large model application development, agent development, skill development) from WeChat public accounts, summarize and send to user's WeChat. Use when you need to regularly collect and push AI industry news.
---

# Daily AI News WeChat

Automatically fetches and summarizes daily AI-related content from WeChat public accounts, then pushes the organized digest to your WeChat.

## What it does

1. **Fetches content**: Retrieves latest articles about large model application development, agent development, and OpenClaw skill development from configured WeChat public accounts
2. **Summarizes**: Extracts title, original link, and generates concise summary of key points
3. **Pushes**: Sends the organized daily digest to your WeChat via OpenClaw messaging

## Configuration

Before first use:
1. Add the WeChat public accounts you want to follow in `references/accounts.md`
2. Verify your OpenClaw WeChat connection is properly configured

## Usage

### Manual run

```python
python scripts/fetch_and_push.py
```

### Scheduled daily run (8:00 AM)

Use OpenClaw cron to schedule:
```json
{
  "name": "Daily AI News Push",
  "schedule": {
    "kind": "cron",
    "expr": "0 8 * * *",
    "tz": "Asia/Shanghai"
  },
  "payload": {
    "kind": "agentTurn",
    "message": "Run daily-ai-news-wechat: fetch latest AI news, summarize, push to WeChat",
    "timeoutSeconds": 300
  },
  "enabled": true
}
```

## Scripts

- `scripts/fetch_and_push.py` - Main script to fetch, summarize and push content
- `scripts/wechat_utils.py` - WeChat API utilities

## References

- `references/accounts.md` - List of WeChat public accounts to follow
- `references/prompt.md` - Summary prompt template
