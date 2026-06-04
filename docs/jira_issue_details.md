# Jira Integration - Issue Details Feature

This document describes the Jira issue details functionality added to engmemory.

## Overview

The `get_issue_details()` function and `engmemory jira-issue` CLI command allow you to fetch detailed information about a specific Jira issue by its ticket ID.

## Features

### Structured Issue Data

The `get_issue_details(issue_key)` function returns a dictionary with the following information:

- **key**: Issue key (e.g., "PROJ-123")
- **summary**: Short description of the issue
- **description**: Full issue description (extracted from ADF format if needed)
- **status**: Current status (e.g., "In Progress", "Done")
- **assignee**: Assignee name or "Unassigned"
- **reporter**: Reporter name
- **created**: Creation timestamp
- **updated**: Last update timestamp
- **priority**: Priority level (e.g., "High", "Medium", "Low")
- **issue_type**: Type of issue (e.g., "Bug", "Story", "Task")
- **labels**: List of labels
- **comments_count**: Number of comments on the issue
- **comments**: List of comment objects, each containing:
  - author: Comment author's display name
  - text: Comment text (extracted from ADF if needed)
  - created: Comment creation timestamp
  - updated: Comment last update timestamp

### ADF Support

The function automatically handles Atlassian Document Format (ADF) for issue descriptions, extracting plain text from the structured format.

## Usage

### Python API

```python
from engmemory.utils.jira import get_issue_details, print_issue_details

# Get issue details as a dictionary
issue = get_issue_details("PROJ-123")
print(f"Issue: {issue['key']}")
print(f"Status: {issue['status']}")
print(f"Description: {issue['description']}")

# Print formatted issue details
print_issue_details("PROJ-123")
```

### CLI Command

```bash
# Display formatted issue details
engmemory jira-issue PROJ-123

# Display raw JSON
engmemory jira-issue PROJ-123 --raw
```

### Example Output (Formatted)

```
================================================================================
JIRA ISSUE: PROJ-123
================================================================================

Summary:      Fix critical bug in authentication module
Type:         Bug
Status:       In Progress
Priority:     High
Assignee:     John Doe
Reporter:     Jane Smith
Created:      2024-01-15T10:30:00.000+0000
Updated:      2024-01-20T14:45:00.000+0000
Comments:     5
Labels:       backend, critical

Description:
--------------------------------------------------------------------------------
Users are experiencing intermittent authentication failures when logging in
through the web interface. This appears to be related to session token
expiration handling.
--------------------------------------------------------------------------------

Comments (5):
--------------------------------------------------------------------------------

[1] John Doe - 2024-01-16T09:00:00.000+0000
    I've started investigating this. It seems to happen after 30 minutes of inactivity.

[2] Jane Smith - 2024-01-17T10:30:00.000+0000
    Could be related to the session timeout configuration in auth.config.js

[3] John Doe - 2024-01-18T14:15:00.000+0000
    Found the issue! The token refresh logic wasn't being triggered properly.
--------------------------------------------------------------------------------
```

### Example Output (Raw JSON)

```json
{
  "key": "PROJ-123",
  "summary": "Fix critical bug in authentication module",
  "description": "Users are experiencing intermittent authentication failures...",
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
      "author": "John Doe",
      "text": "I've started investigating this. It seems to happen after 30 minutes of inactivity.",
      "created": "2024-01-16T09:00:00.000+0000",
      "updated": "2024-01-16T09:00:00.000+0000"
    },
    {
      "author": "Jane Smith",
      "text": "Could be related to the session timeout configuration in auth.config.js",
      "created": "2024-01-17T10:30:00.000+0000",
      "updated": "2024-01-17T10:30:00.000+0000"
    }
  ]
}
```

## Configuration

The Jira issue details feature uses the same configuration as the board listing:

```bash
# Required environment variables
export JIRA_DOMAIN="your-domain.atlassian.net"
export JIRA_EMAIL="your-email@example.com"
export JIRA_API_TOKEN="your-api-token"

# Optional: Set board ID for board-level operations
export JIRA_BOARD_ID="123"
```

See `docs/engmemory.env.example` for a complete configuration template.

## Error Handling

The function provides clear error messages for common issues:

- **Authentication Failed (401)**: Invalid email or API token
- **Issue Not Found (404)**: Invalid issue key or insufficient permissions
- **Missing Configuration**: Required environment variables not set

## API Endpoints Used

- **REST API v3**: `/rest/api/3/issue/{issue_key}`
- **Fields Requested**: summary, description, status, assignee, reporter, created, updated, priority, issuetype, labels, comment

## Implementation Details

### File Structure

```
engmemory/
  utils/
    jira.py              # Contains get_issue_details() and print_issue_details()
    __init__.py          # Exports Jira functions
  cli.py                 # CLI command: engmemory jira-issue
```

### Key Functions

1. **`get_issue_details(issue_key: str) -> Dict`**
   - Fetches issue data from Jira API
   - Extracts and structures relevant fields
   - Handles ADF description format
   - Returns dictionary with structured data

2. **`print_issue_details(issue_key: str)`**
   - Calls `get_issue_details()`
   - Formats and displays issue information
   - Truncates long descriptions for readability

3. **`_extract_text_from_adf(adf_content: Dict) -> str`**
   - Internal helper function
   - Recursively extracts text from ADF nodes
   - Returns plain text string

## Testing

A test script is provided at `test_jira_issue.py`:

```bash
python test_jira_issue.py
```

This test uses mocked API responses to verify:
- Correct data extraction
- ADF description parsing
- Field mapping
- Error handling

## Future Enhancements

Potential improvements for future versions:

1. **Rich Text Support**: Preserve formatting when displaying descriptions
2. **Pagination**: Handle issues with many comments (fetch all pages)
3. **Attachment Info**: Show attached files
4. **Related Issues**: Display linked issues and dependencies
5. **Transition History**: Show status change history
6. **Custom Fields**: Support for project-specific custom fields
7. **Batch Retrieval**: Fetch multiple issues efficiently
8. **Caching**: Cache issue data to reduce API calls
9. **Comment Filtering**: Filter comments by author or date range
10. **Inline Mentions**: Parse and highlight @mentions in comments

## Related Commands

- `engmemory jira`: List issues from a Jira board
- `engmemory jira --raw`: Get raw JSON for board issues

## Support

For issues or questions:
1. Check that your Jira credentials are correctly configured
2. Verify you have permissions to view the issue
3. Ensure the issue key is correctly formatted (e.g., "PROJ-123")
4. Check the Jira API documentation: https://developer.atlassian.com/cloud/jira/platform/rest/v3/
