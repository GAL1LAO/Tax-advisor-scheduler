"""AI Function Tools for Calendar and Email Operations.

This module contains the callable functions that the LLM can invoke to interact with
Google Calendar and Gmail APIs. These functions are registered with the OpenAI LLM
service and can be called during conversations based on user intent.

Core Functions:
    - get_calendar_events: Query calendar for availability on a specific day
    - create_calendar_event: Book appointments and send email confirmations to customers

Authentication:
    Uses Google OAuth 2.0 with credentials.json and auto-generated token.json.
    Required scopes: calendar (read/write), gmail.send

All functions follow the Pipecat FunctionCallParams pattern for async execution
and streaming responses back to the user via text-to-speech.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from loguru import logger
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.services.llm_service import FunctionCallParams
from twilio.rest import Client

load_dotenv(override=True)

# Google API scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',  # Allow creating/reading calendar events
    'https://www.googleapis.com/auth/gmail.send'  # Allow sending emails (changed from readonly)
]

def get_google_credentials():
    """Authenticate and retrieve Google API credentials using OAuth 2.0.

    Handles the complete OAuth flow including:
    - Loading existing tokens from token.json if available
    - Refreshing expired tokens automatically
    - Initiating new OAuth flow if credentials are invalid
    - Saving tokens for future use

    Environment Variables:
        GOOGLE_TOKEN_PATH: Path to token.json (default: "token.json")
        GOOGLE_CREDENTIALS_PATH: Path to credentials.json (default: "credentials.json")

    Returns:
        Credentials: Authenticated Google OAuth2 credentials with calendar and gmail.send scopes

    Raises:
        FileNotFoundError: If credentials.json is not found at the specified path
    """
    creds = None
    token_path = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
    credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    
    # Load existing token if available
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    # If no valid credentials, request authorization
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Google credentials file not found at {credentials_path}. "
                    "Please set GOOGLE_CREDENTIALS_PATH in your .env file or place credentials.json in the project root."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save credentials for next run
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    
    return creds


def parse_relative_date(date_description: str = "today") -> tuple[datetime, datetime]:
    """Convert natural language date descriptions to datetime range.

    Parses conversational date references and converts them to precise datetime objects
    representing the start (00:00:00) and end (23:59:59) of the requested day.

    Supported Formats:
        - Relative: "today", "tomorrow", "yesterday"
        - Weekdays: "monday", "tuesday", etc. or "next monday", "next friday", etc.
        - Periods: "next week"

    Args:
        date_description: Natural language date string (case-insensitive)

    Returns:
        tuple[datetime, datetime]: (day_start, day_end) where:
            - day_start: Beginning of day at 00:00:00
            - day_end: Beginning of next day at 00:00:00 (for range queries)

    Example:
        >>> start, end = parse_relative_date("next monday")
        >>> # Returns datetime range for upcoming Monday
    """
    now = datetime.now()
    date_lower = date_description.lower().strip()

    # Calculate the target date based on the description
    if date_lower in ["today", "now"]:
        target_date = now
    elif date_lower == "tomorrow":
        target_date = now + timedelta(days=1)
    elif date_lower == "yesterday":
        target_date = now - timedelta(days=1)
    elif date_lower in ["next week", "nextweek"]:
        target_date = now + timedelta(weeks=1)
    elif date_lower in ["next monday", "monday"]:
        days_ahead = 0 - now.weekday()  # Monday is 0
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        target_date = now + timedelta(days=days_ahead)
    elif date_lower in ["next tuesday", "tuesday"]:
        days_ahead = 1 - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        target_date = now + timedelta(days=days_ahead)
    elif date_lower in ["next wednesday", "wednesday"]:
        days_ahead = 2 - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        target_date = now + timedelta(days=days_ahead)
    elif date_lower in ["next thursday", "thursday"]:
        days_ahead = 3 - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        target_date = now + timedelta(days=days_ahead)
    elif date_lower in ["next friday", "friday"]:
        days_ahead = 4 - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        target_date = now + timedelta(days=days_ahead)
    elif date_lower in ["next saturday", "saturday"]:
        days_ahead = 5 - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        target_date = now + timedelta(days=days_ahead)
    elif date_lower in ["next sunday", "sunday"]:
        days_ahead = 6 - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        target_date = now + timedelta(days=days_ahead)
    else:
        # Default to today if we can't parse it
        target_date = now

    # Get the start and end of the target date
    day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    return day_start, day_end


async def get_calendar_events(params: FunctionCallParams):
    """Retrieve calendar events for a specified day to check availability.

    LLM-callable function that queries Google Calendar API for events on a given day.
    Filters results to show only timed appointments (excluding all-day events) with
    formatted start/end times for easy readability by the AI assistant.

    IMPORTANT: Automatically filters out events in the past (events that have already started).
    This prevents customers from seeing or booking time slots that have already passed.

    Flow:
        1. Extract date_description from LLM function call arguments
        2. Provide immediate TTS feedback to user
        3. Parse natural language date to datetime range
        4. Query Google Calendar API with UTC time range
        5. Filter to timed events only (ignore all-day events)
        6. Filter out events that have already started (past time slots)
        7. Format times for LLM consumption (e.g., "02:00 PM")
        8. Return JSON array of future events only

    Args:
        params: FunctionCallParams containing:
            - arguments.date_description (str, optional): Natural language date
              (e.g., 'today', 'tomorrow', 'next monday'). Defaults to 'today'
            - llm: Reference to push TTS feedback frames
            - result_callback: Callback to return results to LLM

    Returns:
        str: JSON-formatted string containing array of events with:
            - summary: Event title/description
            - start_time: Formatted start time (e.g., "02:00 PM")
            - end_time: Formatted end time (e.g., "03:00 PM")

    Example Output:
        [
          {
            "summary": "Client Meeting - John Smith",
            "start_time": "02:00 PM",
            "end_time": "03:00 PM"
          }
        ]
    """
    try:
        # Get the date description from params (default to 'today')
        date_description = params.arguments.get('date_description', 'today')

        # Bot speaks immediately before checking schedule
        await params.llm.push_frame(TTSSpeakFrame(f"Let me check the advisor's availability for {date_description}"))

        # Parse the relative date and get the start/end times
        day_start, day_end = parse_relative_date(date_description)

        # Convert to UTC ISO format for Google Calendar API (required format)
        time_min = day_start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        time_max = day_end.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

        logger.info(f"📅 Fetching calendar events for {date_description} ({day_start.strftime('%Y-%m-%d')})")
        
        # Get authenticated calendar service
        creds = get_google_credentials()
        service = build('calendar', 'v3', credentials=creds)
        
        # Fetch events from primary calendar
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            maxResults=50,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])

        # Get current time for filtering past events (timezone-aware)
        now = datetime.now().astimezone()

        # Filter events to include only summary and simplified times (focusing on timed events)
        # Also exclude events that have already started (for "today" queries)
        filtered_events = []
        for event in events:
            # We skip events without a 'dateTime' as they are typically all-day events that don't fit the '12:00 PM meeting' structure of the demo.
            start_time_str = event.get('start', {}).get('dateTime')
            end_time_str = event.get('end', {}).get('dateTime')
            summary = event.get('summary', 'Untitled Event')

            if start_time_str and end_time_str:
                # 1. Parse API string (removes 'Z' and converts to Python object)
                start_dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')).astimezone()
                end_dt = datetime.fromisoformat(end_time_str.replace('Z', '+00:00')).astimezone()

                # Skip events that have already started (only for today)
                # This prevents showing/booking appointments in the past
                if start_dt <= now:
                    continue

                # 2. Format for LLM readability
                start_time = start_dt.strftime("%I:%M %p")
                end_time = end_dt.strftime("%I:%M %p")

                filtered_events.append({
                    'summary': summary,
                    'start_time': start_time,
                    'end_time': end_time
                })
        
        result = json.dumps(filtered_events, indent=2)
        
        # NOTE: events variable in logger will still show max 50 events, but filtered_events is the concise list.
        logger.info(f"✅ Calendar events retrieved: {len(events)} events (Filtered to {len(filtered_events)} timed events)")
        await params.result_callback(result)
        return result
        
    except Exception as e:
        logger.error(f"❌ Failed to get calendar events: {e}")
        error_result = f"Error retrieving calendar events: {str(e)}"
        await params.result_callback(error_result)
        return error_result


async def create_calendar_event(params: FunctionCallParams):
    """Create a calendar appointment and send email confirmation to client.

    LLM-callable function that books an appointment in Google Calendar and automatically
    sends an HTML-formatted confirmation email to the client via Gmail API.

    IMPORTANT: Validates that the appointment time is in the future. Rejects bookings
    for time slots that have already passed to prevent scheduling appointments in the past.

    Flow:
        1. Extract booking details from LLM function call
        2. Provide immediate TTS feedback to user
        3. Parse date and time into datetime objects
        4. Validate appointment is not in the past
        5. Create calendar event with local timezone handling
        6. Send HTML/plain-text confirmation email to customer
        7. Return success confirmation to LLM

    Timezone Handling:
        Uses system local timezone and converts to Etc/GMT format for Google Calendar.
        Ensures appointments appear at correct local time regardless of UTC offset.

    Args:
        params: FunctionCallParams containing:
            - arguments.title (str, required): Event title including client name
            - arguments.date_description (str, required): Natural language date
              (e.g., 'today', 'tomorrow', 'next monday')
            - arguments.start_time (str, required): 24-hour format time (e.g., '14:00')
            - arguments.customer_email (str, required): Client's email for confirmation
            - arguments.duration_minutes (int, optional): Duration in minutes (default: 60)
            - arguments.description (str, optional): Additional notes about appointment
            - llm: Reference to push TTS feedback frames
            - result_callback: Callback to return results to LLM

    Returns:
        str: Success message with appointment details and email confirmation status

    Email Content:
        Sends both plain-text and HTML versions with:
        - Appointment date and time
        - Duration
        - Location (Tax Advisor's Office)
        - Professional formatting

    Example:
        LLM calls with arguments:
        {
            "title": "Appointment with John Smith",
            "date_description": "next monday",
            "start_time": "14:00",
            "customer_email": "john@example.com"
        }
    """
    try:
        # Extract parameters
        title = params.arguments.get('title', 'Untitled Event')
        date_description = params.arguments.get('date_description', 'today')
        start_time = params.arguments.get('start_time', '09:00')
        duration_minutes = int(params.arguments.get('duration_minutes', 60))
        description = params.arguments.get('description', '')
        customer_email = params.arguments.get('customer_email', '')

        # Bot speaks immediately
        await params.llm.push_frame(TTSSpeakFrame(f"Booking your appointment for {date_description}"))

        # Parse the date
        day_start, _ = parse_relative_date(date_description)

        # Parse the start time and create full datetime
        try:
            hour, minute = map(int, start_time.split(':'))
            event_start = day_start.replace(hour=hour, minute=minute)
            event_end = event_start + timedelta(minutes=duration_minutes)
        except ValueError:
            error_msg = f"Invalid time format: {start_time}. Please use HH:MM format (e.g., '14:00')"
            logger.error(f"❌ {error_msg}")
            await params.result_callback(error_msg)
            return error_msg

        # Validate that appointment is not in the past (timezone-aware comparison)
        # Make event_start timezone-aware for proper comparison
        now = datetime.now().astimezone()
        event_start_aware = event_start.replace(tzinfo=now.tzinfo)

        if event_start_aware <= now:
            error_msg = f"Cannot book appointment in the past. The requested time {event_start.strftime('%I:%M %p')} has already passed. Please choose a future time slot."
            logger.error(f"❌ {error_msg}")
            await params.result_callback(error_msg)
            return error_msg

        # Get the local timezone offset in hours
        # datetime.now().astimezone() gives us the local timezone
        local_offset = datetime.now().astimezone().utcoffset()
        offset_hours = int(local_offset.total_seconds() / 3600)

        # Format timezone as Etc/GMT format (note: signs are reversed in Etc/GMT)
        # If offset is +2, we need Etc/GMT-2
        if offset_hours >= 0:
            local_tz_str = f"Etc/GMT-{offset_hours}"
        else:
            local_tz_str = f"Etc/GMT+{abs(offset_hours)}"

        # For the datetime strings, format them without timezone info since we're providing timeZone separately
        start_rfc3339 = event_start.strftime('%Y-%m-%dT%H:%M:%S')
        end_rfc3339 = event_end.strftime('%Y-%m-%dT%H:%M:%S')

        logger.info(f"📅 Creating calendar event: {title} on {event_start.strftime('%Y-%m-%d %I:%M %p')}")

        # Get authenticated calendar service
        creds = get_google_credentials()
        service = build('calendar', 'v3', credentials=creds)

        # Create event object with timezone
        event = {
            'summary': title,
            'description': description,
            'start': {
                'dateTime': start_rfc3339,
                'timeZone': local_tz_str,
            },
            'end': {
                'dateTime': end_rfc3339,
                'timeZone': local_tz_str,
            },
        }

        # Insert the event
        created_event = service.events().insert(calendarId='primary', body=event).execute()

        # Send confirmation email if customer email is provided
        email_sent = False
        if customer_email:
            try:
                # Build Gmail service
                gmail_service = build('gmail', 'v1', credentials=creds)

                # Create email message
                message = MIMEMultipart('alternative')
                message['To'] = customer_email
                message['From'] = 'me'  # 'me' represents the authenticated user
                message['Subject'] = f'Appointment Confirmation - {event_start.strftime("%B %d, %Y")}'

                # Email body (plain text and HTML)
                text_body = f"""
                Dear Client,

                Your appointment has been confirmed!

                Appointment Details:
                - Date: {event_start.strftime('%A, %B %d, %Y')}
                - Time: {event_start.strftime('%I:%M %p')} - {event_end.strftime('%I:%M %p')}
                - Duration: {duration_minutes} minutes
                - Location: Tax Advisor's Office

                If you need to reschedule or cancel, please contact us as soon as possible.

                Best regards,
                Tax Advisory Office
                """

                html_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif;">
                    <h2>Appointment Confirmation</h2>
                    <p>Dear Client,</p>
                    <p>Your appointment has been confirmed!</p>

                    <h3>Appointment Details:</h3>
                    <ul>
                        <li><strong>Date:</strong> {event_start.strftime('%A, %B %d, %Y')}</li>
                        <li><strong>Time:</strong> {event_start.strftime('%I:%M %p')} - {event_end.strftime('%I:%M %p')}</li>
                        <li><strong>Duration:</strong> {duration_minutes} minutes</li>
                        <li><strong>Location:</strong> Tax Advisor's Office</li>
                    </ul>

                    <p>If you need to reschedule or cancel, please contact us as soon as possible.</p>

                    <p>Best regards,<br>Tax Advisory Office</p>
                </body>
                </html>
                """

                # Attach both plain text and HTML versions
                part1 = MIMEText(text_body, 'plain')
                part2 = MIMEText(html_body, 'html')
                message.attach(part1)
                message.attach(part2)

                # Encode message
                raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

                # Send email
                gmail_service.users().messages().send(
                    userId='me',
                    body={'raw': raw_message}
                ).execute()

                email_sent = True
                logger.info(f"✅ Confirmation email sent to {customer_email}")
            except Exception as email_error:
                logger.error(f"⚠️ Failed to send confirmation email: {email_error}")
                # Don't fail the entire operation if email fails

        # Format success message
        result = (
            f"Event created successfully: '{title}' on {event_start.strftime('%A, %B %d')} "
            f"from {event_start.strftime('%I:%M %p')} to {event_end.strftime('%I:%M %p')}"
        )
        if email_sent:
            result += f". Confirmation email sent to {customer_email}"

        logger.info(f"✅ Calendar event created: {created_event.get('htmlLink')}")
        await params.result_callback(result)
        return result

    except Exception as e:
        logger.error(f"❌ Failed to create calendar event: {e}")
        error_result = f"Error creating calendar event: {str(e)}"
        await params.result_callback(error_result)
        return error_result
