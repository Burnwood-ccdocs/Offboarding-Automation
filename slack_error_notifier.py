#!/usr/bin/env python3
"""
Slack Error Notifier - A simple library for sending error notifications to Slack.

This standalone module provides multiple ways to add Slack error notifications
to your Python code with minimal setup.

Usage:
    # 1. Decorator approach
    @slack_error_handler(owners=["U123ABC"])
    def my_function():
        # your code here

    # 2. Context manager approach
    with SlackErrorReporter("my-job", owners=["U123ABC"]):
        # your code here

    # 3. Global exception handler
    setup_error_reporting("my-job", owners=["U123ABC"])
    # your code here

    # 4. Manual notification
    try:
        # your code here
    except Exception as exc:
        notify_failure("my-job", str(exc), owners=["U123ABC"])
        raise
"""

from __future__ import annotations

import functools
import inspect
import os
import sys
import traceback
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Optional, TypeVar, cast

# Try importing slack_sdk, with a helpful error message if not installed
try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    raise ImportError(
        "slack_sdk package is required. Install it with: pip install slack_sdk"
    )

# Type variable for decorator
F = TypeVar("F", bound=Callable[..., Any])

# Module-level configuration
_TOKEN = None  # Will be set when needed
_DEFAULT_CHANNEL = None  # Will be set when needed
_CLIENT = None  # Will be initialized when needed


def _get_client(token: str = None) -> Optional[WebClient]:
    """Get or initialize the Slack client."""
    global _CLIENT, _TOKEN
    
    # If a token is provided, use it
    if token:
        _TOKEN = token
        _CLIENT = WebClient(token=_TOKEN)
        return _CLIENT
    
    # If we already have a client, return it
    if _CLIENT is not None:
        return _CLIENT
    
    # Try to get token from environment
    _TOKEN = os.getenv("SLACK_BOT_TOKEN")
    if not _TOKEN:
        print("[slack_error_notifier] SLACK_BOT_TOKEN env var missing", file=sys.stderr)
        return None
    
    # Initialize client
    _CLIENT = WebClient(token=_TOKEN)
    return _CLIENT


def notify_failure(
    job_name: str, 
    message: str, 
    *, 
    owners: Iterable[str] | None = None, 
    channel: str | None = None,
    token: str | None = None
) -> bool:
    """Send a failure message to Slack.
    
    Args:
        job_name: Name of the job/script that failed
        message: Error message or details about the failure
        owners: List of user IDs to tag (e.g. ["U123ABC"])
        channel: Slack channel ID to send the message to (defaults to SLACK_ERROR_CHANNEL_ID env var)
        token: Slack bot token (defaults to SLACK_BOT_TOKEN env var)
        
    Returns:
        bool: True if the message was sent successfully, False otherwise
    """
    # Get the client
    client = _get_client(token)
    if client is None:
        print("[slack_error_notifier] Slack client not initialized - notification not sent", file=sys.stderr)
        return False
    
    # Get the channel
    global _DEFAULT_CHANNEL
    _DEFAULT_CHANNEL = os.getenv("SLACK_ERROR_CHANNEL_ID")
    target_channel = channel or _DEFAULT_CHANNEL
    if not target_channel:
        print("[slack_error_notifier] No target channel specified", file=sys.stderr)
        return False

    # Format the message
    owners_mention = " ".join(f"<@{uid}>" for uid in owners or [])
    text = (
        f":warning: *{job_name}* failed\n"
        f"{owners_mention}\n```\n"
        f"{message[:1500]}\n"
        f"```"
    )
    
    # Send the message
    try:
        client.chat_postMessage(channel=target_channel, text=text)
        return True
    except Exception as exc:
        print(f"[slack_error_notifier] Slack post failed: {exc}", file=sys.stderr)
        return False


def slack_error_handler(
    job_name: Optional[str] = None,
    owners: Optional[Iterable[str]] = None,
    channel: Optional[str] = None,
    token: Optional[str] = None,
    reraise: bool = True,
) -> Callable[[F], F]:
    """Decorator that catches exceptions and sends them to Slack.
    
    Args:
        job_name: Name of the job/script that might fail. If None, uses the function name.
        owners: List of Slack user IDs to notify. If None, no specific users are tagged.
        channel: Slack channel ID to send the message to (defaults to SLACK_ERROR_CHANNEL_ID env var)
        token: Slack bot token (defaults to SLACK_BOT_TOKEN env var)
        reraise: Whether to re-raise the exception after sending the notification.
        
    Example:
        @slack_error_handler(owners=["U123ABC"])
        def process_data():
            # Your code here
            pass
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal job_name
            if job_name is None:
                job_name = func.__name__
                
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                # Get the full traceback
                exc_info = sys.exc_info()
                tb_lines = traceback.format_exception(*exc_info)
                error_message = "".join(tb_lines)
                
                # Include file and line number
                frame = inspect.trace()[-1]
                filename = os.path.basename(frame[1])
                lineno = frame[2]
                error_message = f"Error in {filename}, line {lineno}:\n{error_message}"
                
                # Send to Slack
                notify_failure(
                    job_name, 
                    error_message, 
                    owners=owners, 
                    channel=channel,
                    token=token
                )
                
                if reraise:
                    raise
                return None
                
        return cast(F, wrapper)
    return decorator


class SlackErrorReporter:
    """Context manager for reporting errors to Slack.
    
    Example:
        with SlackErrorReporter("data-job", owners=["U123ABC"]):
            # Your code here
            process_data()
    """
    
    def __init__(
        self, 
        job_name: str, 
        owners: Optional[Iterable[str]] = None,
        channel: Optional[str] = None,
        token: Optional[str] = None,
        reraise: bool = True
    ) -> None:
        """Initialize the error reporter.
        
        Args:
            job_name: Name of the job/script that might fail
            owners: List of Slack user IDs to notify
            channel: Slack channel ID to send the message to
            token: Slack bot token (defaults to SLACK_BOT_TOKEN env var)
            reraise: Whether to re-raise the exception after sending the notification
        """
        self.job_name = job_name
        self.owners = owners
        self.channel = channel
        self.token = token
        self.reraise = reraise
        
    def __enter__(self) -> SlackErrorReporter:
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            # Get the full traceback
            tb_lines = traceback.format_exception(exc_type, exc_val, exc_tb)
            error_message = "".join(tb_lines)
            
            # Send to Slack
            notify_failure(
                self.job_name, 
                error_message, 
                owners=self.owners, 
                channel=self.channel,
                token=self.token
            )
            
            # Return False to re-raise the exception, True to suppress it
            return not self.reraise
        return False


def setup_error_reporting(
    job_name: str, 
    owners: Optional[Iterable[str]] = None,
    channel: Optional[str] = None,
    token: Optional[str] = None
) -> None:
    """Set up global exception handling to report errors to Slack.
    
    This function installs a global exception hook that will send uncaught
    exceptions to Slack before the program terminates.
    
    Args:
        job_name: Name of the job/script that might fail
        owners: List of Slack user IDs to notify
        channel: Slack channel ID to send the message to
        token: Slack bot token (defaults to SLACK_BOT_TOKEN env var)
    """
    def exception_handler(exc_type, exc_value, exc_traceback):
        # Get the full traceback
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        error_message = "".join(tb_lines)
        
        # Send to Slack
        notify_failure(
            job_name, 
            error_message, 
            owners=owners, 
            channel=channel,
            token=token
        )
        
        # Call the default exception handler
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    
    # Install the custom exception handler
    sys.excepthook = exception_handler


# Simple example of usage
if __name__ == "__main__":
    # Example usage
    print("This is a library meant to be imported, not run directly.")
    print("Here's a simple example of how to use it:")
    print("\nfrom slack_error_notifier import slack_error_handler")
    print("\n@slack_error_handler(owners=['U123ABC'])")
    print("def main():")
    print("    # your code here")
    print("    pass") 