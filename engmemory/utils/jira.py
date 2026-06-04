"""
jira.py

Fetch issues from Jira board for engineering memory integration.
"""

import json
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional, List, Dict

from .config import config


def get_issue_details(issue_key: str) -> Dict:
    """
    Fetch detailed information for a specific Jira issue.
    
    Args:
        issue_key: Jira issue key (e.g., "PROJ-123")
    
    Returns:
        Dictionary containing structured issue details with keys:
        - key: Issue key
        - summary: Issue summary
        - description: Issue description
        - status: Current status
        - assignee: Assignee name (or "Unassigned")
        - reporter: Reporter name
        - created: Creation date
        - updated: Last update date
        - priority: Priority level
        - issue_type: Type of issue (Bug, Story, etc.)
        - labels: List of labels
        - comments_count: Number of comments
        - comments: List of comment dictionaries with author, text, created, updated
    """
    # Get configuration from environment
    domain = config.jira_domain
    email = config.jira_email
    api_token = config.jira_api_token
    
    # Validate configuration
    if not all([domain, email, api_token]):
        raise ValueError(
            "Jira not configured. Set these environment variables:\n"
            "  - JIRA_DOMAIN\n"
            "  - JIRA_EMAIL\n"
            "  - JIRA_API_TOKEN"
        )
    
    # Build URL for specific issue
    url = f"https://{domain}/rest/api/3/issue/{issue_key}"
    
    # Set up headers and authentication
    headers = {"Accept": "application/json"}
    auth = HTTPBasicAuth(email, api_token)
    
    # Query parameters - request specific fields
    query_params = {
        "fields": "summary,description,status,assignee,reporter,created,updated,priority,issuetype,labels,comment"
    }
    
    try:
        # Make the GET request
        response = requests.get(url, headers=headers, auth=auth, params=query_params)
        response.raise_for_status()
        
        # Parse JSON data
        data = response.json()
        fields = data.get("fields", {})
        
        # Extract assignee information
        assignee_obj = fields.get("assignee")
        assignee = assignee_obj.get("displayName") if assignee_obj else "Unassigned"
        
        # Extract reporter information
        reporter_obj = fields.get("reporter", {})
        reporter = reporter_obj.get("displayName", "Unknown")
        
        # Extract status
        status_obj = fields.get("status", {})
        status = status_obj.get("name", "Unknown")
        
        # Extract priority
        priority_obj = fields.get("priority")
        priority = priority_obj.get("name") if priority_obj else "None"
        
        # Extract issue type
        issuetype_obj = fields.get("issuetype", {})
        issue_type = issuetype_obj.get("name", "Unknown")
        
        # Extract description (may be in ADF format or plain text)
        description_obj = fields.get("description")
        if isinstance(description_obj, dict):
            # Atlassian Document Format - extract text content
            description = _extract_text_from_adf(description_obj)
        elif isinstance(description_obj, str):
            description = description_obj
        else:
            description = "No description"
        
        # Extract comments
        comments_obj = fields.get("comment", {})
        comments_count = comments_obj.get("total", 0)
        comments_list = []
        
        # Parse comments if present
        if comments_count > 0:
            raw_comments = comments_obj.get("comments", [])
            for comment in raw_comments:
                author_obj = comment.get("author", {})
                author_name = author_obj.get("displayName", "Unknown")
                
                # Extract comment body (ADF format)
                body_obj = comment.get("body")
                if isinstance(body_obj, dict):
                    comment_text = _extract_text_from_adf(body_obj)
                elif isinstance(body_obj, str):
                    comment_text = body_obj
                else:
                    comment_text = ""
                
                comments_list.append({
                    "author": author_name,
                    "text": comment_text,
                    "created": comment.get("created", ""),
                    "updated": comment.get("updated", "")
                })
        
        # Build structured summary
        issue_details = {
            "key": data.get("key"),
            "summary": fields.get("summary", "No Summary"),
            "description": description,
            "status": status,
            "assignee": assignee,
            "reporter": reporter,
            "created": fields.get("created", ""),
            "updated": fields.get("updated", ""),
            "priority": priority,
            "issue_type": issue_type,
            "labels": fields.get("labels", []),
            "comments_count": comments_count,
            "comments": comments_list
        }
        
        return issue_details
    
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 401:
            raise ValueError(
                "Jira authentication failed. Verify your JIRA_EMAIL and JIRA_API_TOKEN."
            )
        elif response.status_code == 404:
            raise ValueError(f"Issue '{issue_key}' not found. Please verify the issue key.")
        raise Exception(f"Jira HTTP Error: {http_err}")
    
    except Exception as err:
        raise Exception(f"Jira API error: {err}")


def get_issue_full_context(issue_key: str, max_depth: int = 2) -> Dict:
    """
    Recursively fetch a ticket AND all its related context:
    - Parent ticket (epic/story)
    - Subtasks
    - Linked issues (blocks, is blocked by, relates to)
    - Comments on all of these

    This traverses up (parent), down (subtasks), and sideways (links)
    to build the full picture even if the given ticket has no description.

    Args:
        issue_key: Jira issue key (e.g., "KAN-4")
        max_depth: How many levels deep to traverse (default 2)

    Returns:
        Dict with keys:
        - ticket: The main ticket details
        - parent: Parent ticket details (if any)
        - subtasks: List of subtask details
        - linked_issues: List of linked issue details
        - context_summary: Human-readable summary of all gathered context
    """
    domain = config.jira_domain
    email = config.jira_email
    api_token = config.jira_api_token

    if not all([domain, email, api_token]):
        raise ValueError("Jira not configured.")

    visited = set()
    result = {
        "ticket": None,
        "parent": None,
        "subtasks": [],
        "linked_issues": [],
        "all_comments": [],
        "context_summary": "",
    }

    def _fetch_issue_raw(key: str) -> Optional[Dict]:
        """Fetch raw issue data from Jira API with parent/subtask/link fields."""
        if key in visited:
            return None
        visited.add(key)

        url = f"https://{domain}/rest/api/3/issue/{key}"
        headers = {"Accept": "application/json"}
        auth = HTTPBasicAuth(email, api_token)
        params = {
            "fields": "summary,description,status,assignee,reporter,priority,"
                      "issuetype,labels,comment,parent,subtasks,issuelinks"
        }

        try:
            response = requests.get(url, headers=headers, auth=auth, params=params)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def _parse_basic(data: Dict) -> Dict:
        """Parse raw Jira response into a clean dict."""
        fields = data.get("fields", {})
        desc_obj = fields.get("description")
        if isinstance(desc_obj, dict):
            description = _extract_text_from_adf(desc_obj)
        elif isinstance(desc_obj, str):
            description = desc_obj
        else:
            description = ""

        # Parse comments
        comments = []
        comments_obj = fields.get("comment", {})
        for c in comments_obj.get("comments", []):
            body = c.get("body")
            text = _extract_text_from_adf(body) if isinstance(body, dict) else str(body or "")
            if text:
                comments.append({
                    "author": c.get("author", {}).get("displayName", "Unknown"),
                    "text": text,
                    "created": c.get("created", "")[:10],
                })

        status_obj = fields.get("status", {})
        return {
            "key": data.get("key"),
            "summary": fields.get("summary", ""),
            "description": description,
            "status": status_obj.get("name", "Unknown"),
            "issue_type": fields.get("issuetype", {}).get("name", ""),
            "priority": (fields.get("priority") or {}).get("name", "None"),
            "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
            "labels": fields.get("labels", []),
            "comments": comments,
        }

    # --- Fetch the main ticket ---
    main_data = _fetch_issue_raw(issue_key)
    if not main_data:
        raise ValueError(f"Could not fetch {issue_key}")

    result["ticket"] = _parse_basic(main_data)
    result["all_comments"].extend(result["ticket"]["comments"])
    main_fields = main_data.get("fields", {})

    # --- Traverse UP: parent ticket ---
    parent_obj = main_fields.get("parent")
    if parent_obj and max_depth > 0:
        parent_key = parent_obj.get("key")
        if parent_key:
            parent_data = _fetch_issue_raw(parent_key)
            if parent_data:
                result["parent"] = _parse_basic(parent_data)
                result["all_comments"].extend(result["parent"]["comments"])

                # Also get parent's subtasks (siblings of our ticket)
                parent_fields = parent_data.get("fields", {})
                for subtask in parent_fields.get("subtasks", []):
                    sub_key = subtask.get("key")
                    if sub_key and sub_key != issue_key and max_depth > 1:
                        sub_data = _fetch_issue_raw(sub_key)
                        if sub_data:
                            parsed = _parse_basic(sub_data)
                            result["subtasks"].append(parsed)
                            result["all_comments"].extend(parsed["comments"])

    # --- Traverse DOWN: subtasks of the main ticket ---
    for subtask in main_fields.get("subtasks", []):
        sub_key = subtask.get("key")
        if sub_key and sub_key not in visited:
            sub_data = _fetch_issue_raw(sub_key)
            if sub_data:
                parsed = _parse_basic(sub_data)
                result["subtasks"].append(parsed)
                result["all_comments"].extend(parsed["comments"])

    # --- Traverse SIDEWAYS: linked issues ---
    for link in main_fields.get("issuelinks", []):
        link_type = link.get("type", {}).get("name", "relates to")

        # Outward link (this issue → other)
        outward = link.get("outwardIssue")
        if outward and max_depth > 0:
            linked_key = outward.get("key")
            if linked_key:
                linked_data = _fetch_issue_raw(linked_key)
                if linked_data:
                    parsed = _parse_basic(linked_data)
                    parsed["link_type"] = f"{link_type} (outward)"
                    result["linked_issues"].append(parsed)
                    result["all_comments"].extend(parsed["comments"])

        # Inward link (other → this issue)
        inward = link.get("inwardIssue")
        if inward and max_depth > 0:
            linked_key = inward.get("key")
            if linked_key:
                linked_data = _fetch_issue_raw(linked_key)
                if linked_data:
                    parsed = _parse_basic(linked_data)
                    parsed["link_type"] = f"{link_type} (inward)"
                    result["linked_issues"].append(parsed)
                    result["all_comments"].extend(parsed["comments"])

    # --- Build human-readable context summary ---
    result["context_summary"] = _build_traversal_summary(result)

    return result


def _build_traversal_summary(data: Dict) -> str:
    """Build a human-readable summary from the traversal result.
    
    IMPORTANT: Comments are given highest priority because developers
    discuss implementation details, blockers, and decisions in comments
    more than in ticket descriptions.
    """
    parts = []
    ticket = data["ticket"]

    # Main ticket
    parts.append(f"## Main Ticket: {ticket['key']}")
    parts.append(f"**{ticket['summary']}** [{ticket['status']}]")
    parts.append(f"Type: {ticket['issue_type']} | Priority: {ticket['priority']}")
    if ticket["description"]:
        parts.append(f"\n### Description\n{ticket['description']}")

    # Parent (ALWAYS show parent context — requirements often live here)
    if data["parent"]:
        p = data["parent"]
        parts.append(f"\n## Parent Ticket: {p['key']}")
        parts.append(f"**{p['summary']}** [{p['status']}]")
        if p["description"]:
            parts.append(f"\n### Parent Description\n{p['description']}")
        if p["comments"]:
            parts.append(f"\n### Parent Comments ({len(p['comments'])})")
            for c in p["comments"]:
                parts.append(f"  **{c['author']}** ({c['created']}): {c['text']}")

    # Subtasks / siblings (ALWAYS show — see what's been done, what's related)
    if data["subtasks"]:
        parts.append(f"\n## Sibling/Sub Tasks ({len(data['subtasks'])})")
        for s in data["subtasks"]:
            status_icon = "✓" if s["status"].lower() == "done" else "○"
            parts.append(f"  {status_icon} {s['key']}: {s['summary']} [{s['status']}]")
            # Show subtask descriptions too — context might be here
            if s["description"]:
                parts.append(f"    Description: {s['description'][:300]}")
            # Show subtask comments — critical discussions happen here
            if s["comments"]:
                for c in s["comments"]:
                    parts.append(f"    💬 {c['author']} ({c['created']}): {c['text'][:200]}")

    # Linked issues (ALWAYS show — blockers, related bugs, dependencies)
    if data["linked_issues"]:
        parts.append(f"\n## Linked Issues ({len(data['linked_issues'])})")
        for li in data["linked_issues"]:
            link_type = li.get("link_type", "relates to")
            parts.append(f"  → {li['key']}: {li['summary']} [{li['status']}] ({link_type})")
            if li["description"]:
                parts.append(f"    Description: {li['description'][:300]}")
            if li["comments"]:
                for c in li["comments"]:
                    parts.append(f"    💬 {c['author']} ({c['created']}): {c['text'][:200]}")

    # ALL COMMENTS — highest priority section
    # People discuss implementation details, edge cases, bugs, and decisions here
    if data["all_comments"]:
        parts.append(f"\n## 📋 All Discussion ({len(data['all_comments'])} comments across ticket hierarchy)")
        parts.append("(Comments are the primary source of implementation context)")
        for c in data["all_comments"]:
            parts.append(f"\n  **{c['author']}** ({c['created']}):")
            parts.append(f"  {c['text']}")

    return "\n".join(parts)


def search_jira_tickets(query: str, max_results: int = 20) -> List[Dict]:
    """
    Search ALL Jira tickets using JQL text search.
    
    This is used for:
    - Finding past bugs that match a current issue
    - Finding tickets about a topic even if no commit exists
    - Finding external issues (Kafka, server, infra) documented in Jira
    
    Args:
        query: Text to search for (searches summary, description, comments)
        max_results: Max tickets to return
    
    Returns:
        List of matching ticket dicts with key, summary, status, comments
    """
    domain = config.jira_domain
    email = config.jira_email
    api_token = config.jira_api_token

    if not all([domain, email, api_token]):
        return []

    # JQL text search across summary, description, and comments
    # Escape special JQL characters
    safe_query = query.replace('"', '\\"')
    jql = f'text ~ "{safe_query}" ORDER BY updated DESC'

    url = f"https://{domain}/rest/api/3/search/jql"
    headers = {"Accept": "application/json"}
    auth = HTTPBasicAuth(email, api_token)
    params = {
        "jql": jql,
        "maxResults": max_results,
        "fields": "summary,status,description,comment,assignee,issuetype,priority,updated"
    }

    try:
        response = requests.get(url, headers=headers, auth=auth, params=params)
        if response.status_code != 200:
            return []

        data = response.json()
        results = []

        for issue in data.get("issues", []):
            fields = issue.get("fields", {})
            
            # Parse description
            desc_obj = fields.get("description")
            if isinstance(desc_obj, dict):
                description = _extract_text_from_adf(desc_obj)
            elif isinstance(desc_obj, str):
                description = desc_obj
            else:
                description = ""

            # Parse comments
            comments = []
            comments_obj = fields.get("comment", {})
            for c in comments_obj.get("comments", []):
                body = c.get("body")
                text = _extract_text_from_adf(body) if isinstance(body, dict) else str(body or "")
                if text:
                    comments.append({
                        "author": c.get("author", {}).get("displayName", "Unknown"),
                        "text": text,
                        "created": c.get("created", "")[:10],
                    })

            results.append({
                "key": issue.get("key"),
                "summary": fields.get("summary", ""),
                "status": fields.get("status", {}).get("name", "Unknown"),
                "issue_type": fields.get("issuetype", {}).get("name", ""),
                "priority": (fields.get("priority") or {}).get("name", "None"),
                "description": description,
                "comments": comments,
                "updated": fields.get("updated", ""),
            })

        return results

    except Exception:
        return []


def _extract_text_from_adf(adf_content: Dict) -> str:
    """
    Extract plain text from Atlassian Document Format (ADF).
    
    Args:
        adf_content: ADF content dictionary
    
    Returns:
        Plain text string
    """
    if not isinstance(adf_content, dict):
        return str(adf_content)
    
    text_parts = []
    
    def extract_recursive(node):
        if isinstance(node, dict):
            # Extract text from text nodes
            if node.get("type") == "text":
                text_parts.append(node.get("text", ""))
            
            # Recursively process content
            if "content" in node:
                for child in node["content"]:
                    extract_recursive(child)
        
        elif isinstance(node, list):
            for item in node:
                extract_recursive(item)
    
    extract_recursive(adf_content)
    return " ".join(text_parts).strip() or "No description"


def get_jira_issues(board_id: Optional[str] = None, max_results: int = 50) -> List[Dict]:
    """
    Fetch issues from a Jira board.
    
    Args:
        board_id: Jira board ID (uses JIRA_BOARD_ID from env if not provided)
        max_results: Maximum number of issues to fetch
    
    Returns:
        List of issue dictionaries
    """
    # Get configuration from environment
    domain = config.jira_domain
    board = board_id or config.jira_board_id
    email = config.jira_email
    api_token = config.jira_api_token
    
    # Validate configuration
    if not all([domain, board, email, api_token]):
        raise ValueError(
            "Jira not configured. Set these environment variables:\n"
            "  - JIRA_DOMAIN\n"
            "  - JIRA_BOARD_ID\n"
            "  - JIRA_EMAIL\n"
            "  - JIRA_API_TOKEN"
        )
    
    # Build URL
    url = f"https://{domain}/rest/agile/1.0/board/{board}/issue"
    
    # Set up headers and authentication
    headers = {"Accept": "application/json"}
    auth = HTTPBasicAuth(email, api_token)
    
    # Query parameters
    query_params = {
        "fields": "summary,status,assignee,created,updated",
        "maxResults": max_results
    }
    
    try:
        # Make the GET request
        response = requests.get(url, headers=headers, auth=auth, params=query_params)
        response.raise_for_status()
        
        # Parse JSON data
        data = response.json()
        issues = data.get("issues", [])
        
        return issues
    
    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 401:
            raise ValueError(
                "Jira authentication failed. Verify your JIRA_EMAIL and JIRA_API_TOKEN."
            )
        raise Exception(f"Jira HTTP Error: {http_err}")
    
    except Exception as err:
        raise Exception(f"Jira API error: {err}")


def print_jira_issues(board_id: Optional[str] = None):
    """Print Jira issues in a formatted way."""
    try:
        issues = get_jira_issues(board_id)
        
        print(f"--- Successfully retrieved {len(issues)} issues ---\n")
        
        for issue in issues:
            issue_key = issue.get("key")
            fields = issue.get("fields", {})
            
            summary = fields.get("summary", "No Summary")
            status_obj = fields.get("status") or {}
            status_name = status_obj.get("name", "Unknown Status")
            
            print(f"[{status_name:<15}] {issue_key}: {summary}")
    
    except Exception as err:
        print(f"Error: {err}")


def print_issue_details(issue_key: str):
    """Print detailed information for a specific Jira issue in a formatted way."""
    try:
        issue = get_issue_details(issue_key)
        
        print(f"\n{'=' * 80}")
        print(f"JIRA ISSUE: {issue['key']}")
        print(f"{'=' * 80}\n")
        
        print(f"Summary:      {issue['summary']}")
        print(f"Type:         {issue['issue_type']}")
        print(f"Status:       {issue['status']}")
        print(f"Priority:     {issue['priority']}")
        print(f"Assignee:     {issue['assignee']}")
        print(f"Reporter:     {issue['reporter']}")
        print(f"Created:      {issue['created']}")
        print(f"Updated:      {issue['updated']}")
        print(f"Comments:     {issue['comments_count']}")
        
        if issue['labels']:
            print(f"Labels:       {', '.join(issue['labels'])}")
        
        print(f"\nDescription:\n{'-' * 80}")
        # Truncate description if too long
        description = issue['description']
        if len(description) > 500:
            description = description[:500] + "... (truncated)"
        print(description)
        print(f"{'-' * 80}\n")
        
        # Display comments if present
        if issue['comments']:
            print(f"Comments ({len(issue['comments'])}):")
            print(f"{'-' * 80}")
            for idx, comment in enumerate(issue['comments'], 1):
                print(f"\n[{idx}] {comment['author']} - {comment['created']}")
                # Truncate long comments
                comment_text = comment['text']
                if len(comment_text) > 300:
                    comment_text = comment_text[:300] + "... (truncated)"
                print(f"    {comment_text}")
            print(f"{'-' * 80}\n")
    
    except Exception as err:
        print(f"Error fetching issue details: {err}")


# For backward compatibility / testing
if __name__ == "__main__":
    print_jira_issues()