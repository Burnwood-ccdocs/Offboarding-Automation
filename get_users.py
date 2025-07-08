#!/usr/bin/env python3
"""
Script to retrieve, manage and delete users and their calendars from a Go High Level location
"""
import os
import json
import logging
import sys
from datetime import datetime
from dotenv import load_dotenv
import threading
import time
import argparse
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_error_notifier import slack_error_handler


# Import the OAuth client and TwilioPhoneManager from main.py
from main import GoHighLevelOAuth, perform_oauth_flow, TwilioPhoneManager

# Import token refresh helper
from get_token import refresh_tokens

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# Background token refresher
# ---------------------------------------------------------------------------

def _start_token_refresh_daemon(interval_hours: int = 12):
    """Start a daemon thread that refreshes OAuth tokens every `interval_hours`."""

    interval_seconds = interval_hours * 3600

    def _loop():
        while True:
            try:
                logger.info("[TokenRefresher] Running scheduled token refresh…")
                refresh_tokens()
            except Exception as exc:
                logger.error("[TokenRefresher] Token refresh failed: %s", exc)
            time.sleep(interval_seconds)

    # Run one refresh immediately at startup
    try:
        refresh_tokens()
    except Exception as exc:
        logger.error("[TokenRefresher] Initial token refresh failed: %s", exc)

    thread = threading.Thread(target=_loop, daemon=True, name="TokenRefresher")
    thread.start()

# Start the refresher as soon as the module is imported
_start_token_refresh_daemon()

# Go High Level OAuth Configuration
GHL_CLIENT_ID = os.getenv("GHL_CLIENT_ID")
GHL_CLIENT_SECRET = os.getenv("GHL_CLIENT_SECRET")
GHL_REDIRECT_URI = os.getenv("GHL_REDIRECT_URI", "https://login1.theccdocs.com/vicidial/welcome.php")

# Slack Configuration
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
SLACK_BOT_TOKEN      = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN      = os.environ["SLACK_APP_TOKEN"]
AUTHORIZED_USERS     = ["U08MN3MGKRN", "U08EFGBJST0", "U08LVQBDF0E", "U08PPJ3AXE0"]

# initialize Bolt app in Socket Mode
app = App(
    token=SLACK_BOT_TOKEN,
    signing_secret=SLACK_SIGNING_SECRET,
)

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

def get_all_users(oauth_client):
    """
    Retrieve all users from the current location
    
    Args:
        oauth_client: Authenticated GoHighLevelOAuth instance
        
    Returns:
        List of users or None if failed
    """
    if not oauth_client.location_id:
        logger.error("Location ID required to get users")
        return None
    
    # Use v2 API for users endpoint
    endpoint = "/users/"
    
    # Add query parameters - only locationId, as the API doesn't support pagination
    params = {
        "locationId": oauth_client.location_id
    }
    
    try:
        # Override headers for user API
        url = f"{oauth_client.api_base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {oauth_client.access_token}",
            "Content-Type": "application/json",
            "Version": "2021-07-28"  # Specific version for user API
        }
        
        import requests
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code in [200, 201]:
            response_data = response.json()
            users = response_data.get("users", [])
            total = len(users)
            
            logger.info(f"Retrieved {total} users")
            return users
        else:
            logger.error(f"API request failed: GET {endpoint} - {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error retrieving users: {e}")
        return None

def find_user_by_email(oauth_client, email):
    """
    Find a user by email
    
    Args:
        oauth_client: Authenticated GoHighLevelOAuth instance
        email: Email address to search for
        
    Returns:
        User object if found, None otherwise
    """
    if not oauth_client.location_id:
        logger.error("Location ID required to find user")
        return None
    
    # Get all users for the location
    endpoint = "/users/"
    
    try:
        # Make API request
        response = oauth_client.make_api_request("GET", endpoint)
        
        if response:
            # Handle the case where response might not be a list
            users = []
            if isinstance(response, list):
                users = response
            elif isinstance(response, dict) and 'users' in response:
                users = response.get('users', [])
            else:
                logger.warning(f"Unexpected user response type: {type(response)}")
                
            # Find user with matching email
            for user in users:
                if user.get("email", "").lower() == email.lower():
                    logger.info(f"Found user with email {email}: {user.get('id')}")
                    return user
            
            logger.info(f"No user found with email {email}")
            return None
        else:
            logger.error("Failed to retrieve users")
            return None
            
    except Exception as e:
        logger.error(f"Error finding user by email: {e}")
        return None

def get_user_by_id(oauth_client, user_id):
    """
    Get user details by ID
    
    Args:
        oauth_client: Authenticated GoHighLevelOAuth instance
        user_id: User ID to get details for
        
    Returns:
        User object if found, None otherwise
    """
    if not oauth_client.location_id or not user_id:
        logger.error("Location ID and User ID required to get user details")
        return None
    
    endpoint = f"/users/{user_id}"
    
    try:
        # Make API request
        response = oauth_client.make_api_request("GET", endpoint)
        
        if response:
            logger.info(f"Retrieved user details for ID: {user_id}")
            return response
        else:
            logger.error(f"Failed to retrieve user with ID: {user_id}")
            return None
            
    except Exception as e:
        logger.error(f"Error retrieving user by ID: {e}")
        return None

def get_user_calendars(oauth_client, user_id):
    """
    Get calendars associated with a user
    
    Args:
        oauth_client: Authenticated GoHighLevelOAuth instance
        user_id: User ID to get calendars for
        
    Returns:
        List of calendars or empty list if none found
    """
    if not oauth_client.location_id or not user_id:
        logger.error("Location ID and User ID required to get calendars")
        return []
    
    # Get all calendars for the location
    endpoint = "/calendars/"
    
    try:
        # Make API request
        response = oauth_client.make_api_request("GET", endpoint)
        
        if response:
            # Handle different response formats
            calendars = []
            
            if isinstance(response, str):
                logger.warning("Calendar API returned a string response, attempting to parse as JSON")
                import json
                try:
                    parsed_response = json.loads(response)
                    if isinstance(parsed_response, list):
                        calendars = parsed_response
                    elif isinstance(parsed_response, dict) and 'calendars' in parsed_response:
                        calendars = parsed_response.get('calendars', [])
                    else:
                        logger.warning(f"Unexpected JSON structure in calendar response")
                except json.JSONDecodeError:
                    logger.error("Failed to parse calendar response as JSON")
                    return []
            elif isinstance(response, list):
                calendars = response
            elif isinstance(response, dict):
                # Handle dictionary response format
                if 'calendars' in response:
                    calendars = response.get('calendars', [])
                else:
                    logger.warning(f"Unexpected dictionary structure in calendar response")
                    # Try to extract any list that might contain calendars
                    for key, value in response.items():
                        if isinstance(value, list) and len(value) > 0:
                            calendars = value
                            logger.info(f"Found potential calendar list in key: {key}")
                            break
            else:
                logger.warning(f"Unexpected calendar response type: {type(response)}")
            
            # Filter calendars to find those associated with the user
            user_calendars = []
            
            for calendar in calendars:
                # Check if the user is a team member in this calendar
                team_members = calendar.get("teamMembers", [])
                
                for member in team_members:
                    if member.get("userId") == user_id:
                        user_calendars.append(calendar)
                        break
            
            logger.info(f"Found {len(user_calendars)} calendars associated with user {user_id}")
            return user_calendars
        else:
            logger.info("No calendars found or empty response")
            return []
            
    except Exception as e:
        logger.error(f"Error retrieving calendars: {e}")
        return []

def delete_calendar(oauth_client, calendar_id):
    """
    Delete a calendar
    
    Args:
        oauth_client: Authenticated GoHighLevelOAuth instance
        calendar_id: Calendar ID to delete
        
    Returns:
        True if successful, False otherwise
    """
    if not calendar_id:
        logger.error("Calendar ID required for deletion")
        return False
    
    endpoint = f"/calendars/{calendar_id}"
    
    try:
        # Make API request
        response = oauth_client.make_api_request("DELETE", endpoint)
        
        if response:
            logger.info(f"Successfully deleted calendar {calendar_id}")
            return True
        else:
            logger.error(f"Failed to delete calendar {calendar_id}")
            return False
            
    except Exception as e:
        logger.error(f"Error deleting calendar {calendar_id}: {e}")
        return False

def find_phone_number_sid(phone_number):
    """
    Find the SID for a phone number in Twilio
    
    Args:
        phone_number: Phone number in E.164 format (e.g., +15551234567)
        
    Returns:
        SID of the phone number if found, None otherwise
    """
    if not phone_number:
        logger.error("Phone number required to find SID")
        return None
    
    # Initialize Twilio client
    try:
        twilio_manager = TwilioPhoneManager(
            account_sid=TWILIO_ACCOUNT_SID,
            auth_token=TWILIO_AUTH_TOKEN
        )
        
        # Get all account numbers
        account_numbers = twilio_manager.get_account_numbers(limit=100)
        
        # Find the number that matches
        for number in account_numbers:
            if number['phone_number'] == phone_number:
                logger.info(f"Found phone number {phone_number} with SID: {number['sid']}")
                return number['sid']
        
        logger.warning(f"No phone number found matching {phone_number}")
        return None
    except Exception as e:
        logger.error(f"Error finding phone number SID: {e}")
        return None

def release_phone_number(phone_number):
    """
    Release a phone number from Twilio
    
    Args:
        phone_number: Phone number in E.164 format (e.g., +15551234567)
        
    Returns:
        True if successful, False otherwise
    """
    if not phone_number:
        logger.error("Phone number required for release")
        return False
    
    # Find the SID for the phone number
    number_sid = find_phone_number_sid(phone_number)
    if not number_sid:
        logger.warning(f"Cannot release phone number {phone_number}: SID not found")
        return False
    
    # Initialize Twilio client
    try:
        twilio_manager = TwilioPhoneManager(
            account_sid=TWILIO_ACCOUNT_SID,
            auth_token=TWILIO_AUTH_TOKEN
        )
        
        # Release the number
        result = twilio_manager.release_phone_number(number_sid)
        if result:
            logger.info(f"Successfully released phone number {phone_number}")
            return True
        else:
            logger.error(f"Failed to release phone number {phone_number}")
            return False
    except Exception as e:
        logger.error(f"Error releasing phone number: {e}")
        return False

def delete_user(oauth_client, user_id):
    """
    Deletes a user in Go High Level. This function only performs the final user deletion.
    
    Args:
        oauth_client: Authenticated GoHighLevelOAuth instance
        user_id: User ID to delete
        
    Returns:
        True if successful, False otherwise
    """
    if not user_id:
        logger.error("User ID required to delete user")
        return False
        
    logger.info(f"Submitting final request to delete user ID: {user_id}")
    endpoint = f"/users/{user_id}"
    
    try:
        response = oauth_client.make_api_request("DELETE", endpoint)
        if response is not None:
            logger.info(f"API call to delete user {user_id} was successful.")
            return True
        else:
            logger.error(f"API call to delete user {user_id} failed.")
            return False
    except Exception as e:
        logger.error(f"An exception occurred while deleting user {user_id}: {e}")
        return False

def save_users_to_file(users, filename=None):
    """
    Save users to a JSON file
    
    Args:
        users: List of user objects
        filename: Optional filename (default: users_YYYY-MM-DD.json)
        
    Returns:
        Path to saved file
    """
    if filename is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"users_{date_str}.json"
    
    try:
        with open(filename, "w") as f:
            json.dump(users, f, indent=2)
        logger.info(f"Saved {len(users)} users to {filename}")
        return filename
    except Exception as e:
        logger.error(f"Error saving users to file: {e}")
        return None

@slack_error_handler(
    job_name="client_offboarding",
    owners=["U08PPJ3AXE0"],  # Notify this specific user on errors
    reraise=True
)
def delete_user_and_calendars(oauth_client, email, confirm=True, release_phone=True):
    """
    Finds a user by email and completely offboards them by deleting their calendars,
    releasing their Twilio phone number, and finally deleting their user account.

    Args:
        oauth_client: Authenticated GoHighLevelOAuth instance
        email: Email address of the user to delete
        confirm: If True, prompt for confirmation in the console.
        release_phone: If True, attempt to release the user's Twilio phone number.

    Returns:
        True if the user was successfully offboarded, False otherwise.
    """
    # 1. Find the user by email
    user = find_user_by_email(oauth_client, email)
    if not user:
        # find_user_by_email already logs the error
        return False

    user_id = user.get("id")
    user_name = f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
    logger.info(f"Found user to offboard: {user_name} ({email}) with ID: {user_id}")

    # 2. Get phone number info before confirmation prompt
    phone_number_to_release = None
    if release_phone:
        location_id = oauth_client.location_id
        if "lcPhone" in user and user["lcPhone"].get(location_id):
            phone_number_to_release = user["lcPhone"].get(location_id)
            logger.info(f"User has phone number {phone_number_to_release} eligible for release.")

    # 3. Ask for confirmation if required (for CLI usage)
    if confirm:
        print(f"\nProceeding to offboard {user_name} ({email}).")
        print("This will involve:")
        print("  - Deleting all associated calendars.")
        if phone_number_to_release:
            print(f"  - Releasing the Twilio phone number: {phone_number_to_release}")
        print("  - Permanently deleting the user account.")
        
        confirmation = input("Are you sure you want to continue? Type 'yes' to confirm: ")
        if confirmation.lower() != "yes":
            logger.info("User offboarding cancelled by user.")
            return False

    # 4. Get and delete user's calendars
    calendars = get_user_calendars(oauth_client, user_id)
    if calendars:
        logger.info(f"Found {len(calendars)} calendars to delete for user {user_id}.")
        for calendar in calendars:
            calendar_id = calendar.get("id")
            if calendar_id:
                delete_calendar(oauth_client, calendar_id)
    else:
        logger.info(f"No calendars found for user {user_id}.")

    # 5. Release phone number if it exists
    if phone_number_to_release:
        if release_phone_number(phone_number_to_release):
            logger.info(f"Successfully released phone number {phone_number_to_release}.")
        else:
            logger.warning(f"Failed to release phone number {phone_number_to_release}.")

    # 6. Delete the user
    if delete_user(oauth_client, user_id):
        logger.info(f"Successfully offboarded user {user_name} ({email}).")
        return True
    else:
        logger.error(f"Failed to complete offboarding for user {user_name} ({email}).")
        return False

def print_user(user):
    """
    Print detailed information about a user
    
    Args:
        user: User object to print
    """
    if not user:
        return
    
    user_id = user.get("id", "N/A")
    first_name = user.get("firstName", "")
    last_name = user.get("lastName", "")
    name = f"{first_name} {last_name}".strip()
    email = user.get("email", "N/A")
    phone = user.get("phone", "N/A")
    role = user.get("role", "N/A")
    status = user.get("status", "active")
    created_at = user.get("createdAt", "Unknown")
    
    print(f"ID:         {user_id}")
    print(f"Name:       {name}")
    print(f"Email:      {email}")
    print(f"Phone:      {phone}")
    print(f"Role:       {role}")
    print(f"Status:     {status}")
    print(f"Created:    {created_at}")
    
    # Print location access if available
    location_ids = user.get("locationIds", [])
    if location_ids:
        print(f"Locations:  {', '.join(location_ids)}")
    
    # Print CRM phone number if available
    if "lcPhone" in user:
        for location_id, phone_number in user["lcPhone"].items():
            print(f"CRM Phone:  {phone_number} (Location: {location_id})")

def print_users(users):
    """
    Print a list of users in a formatted table
    
    Args:
        users: List of user objects to print
    """
    if not users:
        print("No users to display")
        return
    
    print(f"\nFound {len(users)} users:")
    print("-"*100)
    print(f"{'ID':<24} {'Name':<25} {'Email':<30} {'Role':<10} {'CRM Phone':<15}")
    print("-"*100)
    
    for user in users:
        user_id = user.get("id", "N/A")
        first_name = user.get("firstName", "")
        last_name = user.get("lastName", "")
        name = f"{first_name} {last_name}".strip()
        email = user.get("email", "N/A")
        role = user.get("role", "N/A")
        
        # Get CRM phone if available
        crm_phone = "None"
        if "lcPhone" in user:
            for location_id, phone_number in user["lcPhone"].items():
                crm_phone = phone_number
                break
        
        print(f"{user_id:<24} {name[:25]:<25} {email[:30]:<30} {role[:10]:<10} {crm_phone:<15}")
    
    print("-"*100)

@app.command("/offboardclient")
@slack_error_handler(
    job_name="slack_offboard_command",
    owners=["U08PPJ3AXE0"],  # Notify this specific user on errors
    reraise=False  # Don't reraise so the Slack command can still respond gracefully
)
def handle_offboard(ack, body, client):
    try:
        # ack() first — this immediately tells Slack you received the command
        ack()

        user_id = body["user_id"]
        channel_id = body["channel_id"]
        
        # Log the request details for debugging
        logger.info(f"Received /offboardclient command from user {user_id} in channel {channel_id}")
        logger.info(f"Full body: {body}")
        
        # Check if the user is authorized
        if user_id not in AUTHORIZED_USERS:
            logger.warning(f"Unauthorized user {user_id} attempted to use /offboard")
            try:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=":no_entry: You are not authorized to use this command."
                )
            except Exception as e:
                logger.error(       
                    f"Could not send unauthorized message to user {user_id} in channel {channel_id}. "
                    f"The bot may not be in this channel. Error: {e}"
                )
            return

        # Validate email format
        text = body.get("text", "").strip()
        email = text.split()[0] if text else ""
        if not email or "@" not in email:
            try:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=":warning: Please supply a valid email, e.g. `/offboardclient alice@example.com`."
                )
            except Exception as e:
                logger.error(
                    f"Could not send validation error message to user {user_id} in channel {channel_id}. "
                    f"The bot may not be in this channel. Error: {e}"
                )
            return
        
        # Send processing message
        try:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f":hourglass_flowing_sand: Processing offboard request for `{email}`..."
            )
        except Exception as e:
            logger.error(f"Could not send processing message to user {user_id}: {e}")

        # Perform the offboarding
        oauth = GoHighLevelOAuth(
            client_id     = os.getenv("GHL_CLIENT_ID"),
            client_secret = os.getenv("GHL_CLIENT_SECRET"),
            redirect_uri  = os.getenv("GHL_REDIRECT_URI")
        )
        if not perform_oauth_flow(oauth):
            result = False
        else:
            # Call the main offboarding function without confirmation
            result = delete_user_and_calendars(
                oauth,
                email,
                confirm=False,
                release_phone=True
            )

        # Report the result
        logger.info(f"Offboarding result for {email}: {result}")
        if result:
            ephemeral_text = f":white_check_mark: Successfully offboarded `{email}` and removed their calendars."
            public_text = f":wave: <@{user_id}> has offboarded user `{email}` from the system."
            logger.info(f"Preparing to send success messages for {email}")
        else:
            ephemeral_text = f":x: Failed to offboard `{email}`. Check logs for details."
            public_text = None
            logger.info(f"Preparing to send failure message for {email}")

        # Send ephemeral message to the user who issued the command
        try:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=ephemeral_text
            )
        except Exception as e:
            logger.error(
                f"Could not send completion message to user {user_id} in channel {channel_id}. "
                f"The bot may not be in this channel. Error: {e}"
            )

        # Send public message to the channel if offboarding was successful
        if result and public_text:
            try:
                logger.info(f"Posting public message to channel {channel_id}: {public_text}")
                client.chat_postMessage(
                    channel=channel_id,
                    text=public_text
                )
                logger.info("Public message posted successfully")
            except Exception as e:
                logger.error(
                    f"Could not send public notification to channel {channel_id}. "
                    f"Make sure the bot is added to the channel. Error: {e}"
                )
    
    except Exception as e:
        logger.error(f"Unexpected error in handle_offboard: {e}", exc_info=True)
        # Try to send an error message to the user if we have the necessary info
        try:
            user_id = body.get("user_id") if 'body' in locals() else None
            channel_id = body.get("channel_id") if 'body' in locals() else None
            if user_id and channel_id:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=":x: An unexpected error occurred while processing your request. Please check the logs."
                )
        except Exception as nested_e:
            logger.error(f"Failed to send error message to user: {nested_e}")

# Add a simple test command
@app.command("/test")
def handle_test(ack, body, client):
    ack()
    logger.info("Test command received!")
    try:
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=body["user_id"],
            text="🤖 Bot is working!"
        )
        logger.info("Test response sent successfully")
    except Exception as e:
        logger.error(f"Test command failed: {e}")

# Add global error listener
@app.error
def global_error_handler(error, body, logger):
    logger.error(f"Global error handler caught: {error}", exc_info=True)
    logger.error(f"Request body: {body}")
    # Return False to let the default error handler run as well
    return False

def main():
    """Main function to run the script"""
    parser = argparse.ArgumentParser(description="Go High Level User Management Tool")
    parser.add_argument("--location", help="Location ID to use (overrides saved location)")
    parser.add_argument("--list", action="store_true", help="List all users in the location")
    parser.add_argument("--save", action="store_true", help="Save user list to JSON file")
    parser.add_argument("--find", help="Find user by email address")
    parser.add_argument("--delete", help="Delete user by email address")
    parser.add_argument("--force", action="store_true", help="Force delete without confirmation")
    parser.add_argument("--calendars", action="store_true", help="List calendars for the found user")
    parser.add_argument("--keep-phone", action="store_true", help="Don't release phone number when deleting user")
    
    args = parser.parse_args()
    
    # Initialize OAuth client
    oauth_client = GoHighLevelOAuth(
        client_id=GHL_CLIENT_ID,
        client_secret=GHL_CLIENT_SECRET,
        redirect_uri=GHL_REDIRECT_URI
    )
    
    # Perform OAuth flow
    if not perform_oauth_flow(oauth_client):
        logger.error("OAuth authentication failed")
        return
    
    # Override location ID if provided
    if args.location:
        oauth_client.location_id = args.location
        logger.info(f"Using location ID: {oauth_client.location_id}")
    
    # List all users
    if args.list:
        users = get_all_users(oauth_client)
        if users:
            print_users(users)
            
            # Save to JSON file if requested
            if args.save:
                save_users_to_file(users)
        else:
            logger.error("No users found or error retrieving users")
    
    # Find user by email
    elif args.find:
        user = find_user_by_email(oauth_client, args.find)
        if user:
            print("\nUser found:")
            print_user(user)
            
            # List calendars for this user if requested
            if args.calendars:
                calendars = get_user_calendars(oauth_client, user.get("id"))
                if calendars and len(calendars) > 0:
                    print(f"\nCalendars for {user.get('firstName')} {user.get('lastName')}:")
                    for calendar in calendars:
                        print(f"  - {calendar.get('name', 'Unknown')} (ID: {calendar.get('id', 'Unknown')})")
                else:
                    print("\nNo calendars found for this user")
        else:
            print(f"\nNo user found with email: {args.find}")
    
    # Delete user by email
    elif args.delete:
        # This now calls the main offboarding orchestrator function
        success = delete_user_and_calendars(
            oauth_client,
            args.delete,
            confirm=not args.force,
            release_phone=not args.keep_phone
        )
        
        if success:
            print(f"\nUser with email {args.delete} was successfully offboarded.")
        else:
            print(f"\nFailed to offboard user with email {args.delete}. Please check logs.")
    
    # No arguments provided
    else:
        parser.print_help()

if __name__ == "__main__":
    # Set up global error reporting for uncaught exceptions
    from slack_error_notifier import setup_error_reporting
    setup_error_reporting(
        job_name="client_offboarding_bot",
        owners=["U08PPJ3AXE0"]  # Notify this specific user on errors
    )
    
    logger.info("Starting Slack bot in Socket Mode...")
    logger.info(f"Bot token: {SLACK_BOT_TOKEN[:10]}...")
    logger.info(f"App token: {SLACK_APP_TOKEN[:10]}...")
    logger.info("Registering command handlers...")
    
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    logger.info("Socket mode handler created, starting connection...")
    handler.start()
    logger.info("Slack bot started successfully!") 
