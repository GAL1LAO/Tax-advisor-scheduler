"""Bot tool functions for Calendar, Gmail, and WhatsApp.

Provides functions for fetching calendar events, Gmail emails, and sending WhatsApp reminders.
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
    """Get authenticated Google credentials for Calendar and Gmail APIs.
    
    Returns:
        Credentials: Authenticated Google OAuth2 credentials
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
    """Parse relative date descriptions like 'today', 'tomorrow', 'next week' into date range.

    Args:
        date_description: Natural language date description (e.g., 'today', 'tomorrow', 'next monday')

    Returns:
        tuple: (start_datetime, end_datetime) for the requested day
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
    """Get calendar events for a specified day (today, tomorrow, next week, etc.).

    Args:
        params: FunctionCallParams with optional 'date_description' argument
                (e.g., 'today', 'tomorrow', 'next monday')

    Returns:
        str: JSON string of events for the specified day
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
        
        # Filter events to include only summary and simplified times (focusing on timed events)
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
    """Create a new calendar event.

    Args:
        params: FunctionCallParams with arguments:
                - title: Event title/summary
                - date_description: Natural language date (e.g., 'today', 'tomorrow', 'next monday')
                - start_time: Start time in 24h format (e.g., '14:00', '09:30')
                - duration_minutes: Duration in minutes (default: 60)
                - description: Optional event description

    Returns:
        str: Confirmation message with event details
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


async def get_gmail_emails(params: FunctionCallParams):
    """Get the 2 most recent Gmail emails.
    
    Args:
        params: FunctionCallParams (no arguments needed)
        
    Returns:
        str: JSON string of 2 most recent emails
    """
    try:
        # Bot speaks immediately before checking inbox
        await params.llm.push_frame(TTSSpeakFrame("Let me check your inbox"))
        
        logger.info(f"📧 Fetching 2 most recent Gmail emails")
        
        # Get authenticated Gmail service
        creds = get_google_credentials()
        service = build('gmail', 'v1', credentials=creds)
        
        # Get message IDs (list() only returns IDs, not full emails)
        message_ids = service.users().messages().list(
            userId='me',
            maxResults=2
        ).execute().get('messages', [])
        
        # Extract snippet, subject, and from for each email
        emails_list = []
        for msg in message_ids:
            message = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='metadata'
            ).execute()
            
            # Extract snippet, subject, and from
            snippet = message['snippet']
            headers = message['payload']['headers']
            subject = next(h['value'] for h in headers if h['name'] == 'Subject')
            sender = next(h['value'] for h in headers if h['name'] == 'From')
            
            emails_list.append({
                'snippet': snippet,
                'subject': subject,
                'from': sender
            })
        
        result = json.dumps(emails_list, indent=2)
        
        logger.info(f"✅ Gmail emails retrieved: {len(emails_list)} emails")
        await params.result_callback(result)
        return result
        
    except Exception as e:
        logger.error(f"❌ Failed to get Gmail emails: {e}")
        error_result = f"Error retrieving Gmail emails: {str(e)}"
        await params.result_callback(error_result)
        return error_result
