"""
Slack integration module for EngMemory.

Auto-creates Slack channels for Jira tickets and captures team discussions.
"""

from engmemory.slack.client import SlackClient
from engmemory.slack.channel_manager import ChannelManager
from engmemory.slack.message_capture import MessageCapture

__all__ = ["SlackClient", "ChannelManager", "MessageCapture"]
