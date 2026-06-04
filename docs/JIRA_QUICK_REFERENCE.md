# Quick Reference: Jira Issue Details with Comments

## CLI Usage

```bash
# Get issue details (formatted)
engmemory jira-issue PROJ-123

# Get issue details (JSON)
engmemory jira-issue PROJ-123 --raw
```

## Python API Usage

### Get Issue Details
```python
from engmemory.utils.jira import get_issue_details

issue = get_issue_details("PROJ-123")

# Access basic info
print(f"Summary: {issue['summary']}")
print(f"Status: {issue['status']}")
print(f"Assignee: {issue['assignee']}")

# Access comments
print(f"\nComments ({issue['comments_count']}):")
for comment in issue['comments']:
    print(f"  {comment['author']}: {comment['text']}")
```

### Print Formatted Details
```python
from engmemory.utils.jira import print_issue_details

print_issue_details("PROJ-123")
```

## Returned Data Structure

```python
{
    "key": "PROJ-123",
    "summary": "Issue summary",
    "description": "Issue description",
    "status": "In Progress",
    "assignee": "John Doe",
    "reporter": "Jane Smith",
    "created": "2024-01-15T10:30:00.000+0000",
    "updated": "2024-01-20T14:45:00.000+0000",
    "priority": "High",
    "issue_type": "Bug",
    "labels": ["backend", "critical"],
    "comments_count": 5,
    "comments": [
        {
            "author": "Alice Developer",
            "text": "Comment text here",
            "created": "2024-01-16T09:00:00.000+0000",
            "updated": "2024-01-16T09:00:00.000+0000"
        }
    ]
}
```

## Common Use Cases

### 1. Extract All Comment Authors
```python
issue = get_issue_details("PROJ-123")
authors = {comment['author'] for comment in issue['comments']}
print(f"Contributors: {', '.join(authors)}")
```

### 2. Get Latest Comment
```python
issue = get_issue_details("PROJ-123")
if issue['comments']:
    latest = issue['comments'][-1]
    print(f"Last comment by {latest['author']}: {latest['text']}")
```

### 3. Search Comments
```python
issue = get_issue_details("PROJ-123")
keyword = "security"
matches = [c for c in issue['comments'] if keyword in c['text'].lower()]
print(f"Found {len(matches)} comments mentioning '{keyword}'")
```

### 4. Filter by Author
```python
issue = get_issue_details("PROJ-123")
author = "John Doe"
author_comments = [c for c in issue['comments'] if c['author'] == author]
print(f"{author} made {len(author_comments)} comments")
```

### 5. Timeline Analysis
```python
from datetime import datetime

issue = get_issue_details("PROJ-123")
for comment in issue['comments']:
    timestamp = datetime.fromisoformat(comment['created'].replace('+0530', ''))
    print(f"{timestamp.strftime('%Y-%m-%d')}: {comment['author']}")
```

### 6. Export to Markdown
```python
issue = get_issue_details("PROJ-123")

md = f"# {issue['key']}: {issue['summary']}\n\n"
md += f"**Status**: {issue['status']}  \n"
md += f"**Assignee**: {issue['assignee']}  \n\n"
md += f"## Description\n{issue['description']}\n\n"
md += f"## Comments ({issue['comments_count']})\n\n"

for comment in issue['comments']:
    md += f"**{comment['author']}** - {comment['created']}  \n"
    md += f"{comment['text']}\n\n"

with open(f"{issue['key']}.md", "w") as f:
    f.write(md)
```

### 7. Sentiment Analysis (with LLM)
```python
from engmemory.analysis import analyze_with_llm

issue = get_issue_details("PROJ-123")
comment_text = "\n".join([f"{c['author']}: {c['text']}" for c in issue['comments']])

prompt = f"Analyze the sentiment and key points in these comments:\n{comment_text}"
analysis = analyze_with_llm(prompt)
print(analysis)
```

## Configuration

Set these environment variables:
```bash
export JIRA_DOMAIN="your-domain.atlassian.net"
export JIRA_EMAIL="your-email@example.com"
export JIRA_API_TOKEN="your-api-token"
```

## Error Handling

```python
from engmemory.utils.jira import get_issue_details

try:
    issue = get_issue_details("PROJ-123")
    print(f"Found issue: {issue['summary']}")
except ValueError as e:
    print(f"Configuration or access error: {e}")
except Exception as e:
    print(f"API error: {e}")
```

## Tips

1. **Empty Comments**: If `comments` is an empty list, the issue has no comments
2. **Truncation**: In formatted output, long comments are truncated (not in JSON)
3. **ADF Format**: Comment text is automatically extracted from Atlassian Document Format
4. **Timestamps**: All timestamps are in ISO 8601 format with timezone
5. **Performance**: Fetching many issues? Consider caching results

## See Also

- Full documentation: `docs/jira_issue_details.md`
- Implementation details: `JIRA_ISSUE_IMPLEMENTATION.md`
- Comments feature: `COMMENTS_FEATURE_ADDED.md`
