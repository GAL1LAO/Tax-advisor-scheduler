# Project Overview: Technical Documentation

**Developer-focused architecture and code documentation**

This document explains the technical implementation, code organization, and how components interact. For setup and usage instructions, see [README.md](README.md).

---

## File Structure & Purpose

### Application Code

#### `bot.py` - Pipeline Orchestration
**Role**: Main application entry point that assembles the voice AI pipeline

**Core Responsibilities**:
- Instantiates AI services (STT, LLM, TTS)
- Defines LLM function tool schemas
- Registers Python functions with OpenAI function calling
- Configures pipeline component order
- Manages transport event handlers (client connect/disconnect)
- Defines AI assistant system prompt and personality

**Key Functions**:
- `run_bot()` - Initializes services, registers tools, builds pipeline
- `bot()` - Creates transport layer with VAD/turn analysis parameters

**Pipeline Order** (lines 199-211):
```
transport.input() → rtvi → stt_mute_filter → stt → context_aggregator.user()
→ llm → tts → transport.output() → context_aggregator.assistant()
```

---

#### `functions.py` - LLM Function Tools
**Role**: Backend logic for AI-callable functions

**Core Responsibilities**:
- Google OAuth 2.0 authentication flow
- Natural language date parsing
- Google Calendar API operations (read events, create events)
- Gmail API operations (send confirmation emails to customers)
- Email template generation (HTML + plain text)

**Function Signatures** (Pipecat pattern):
All functions follow: `async def function_name(params: FunctionCallParams)`

**Key Functions**:

| Function | Purpose | Google API Used | Returns |
|----------|---------|-----------------|---------|
| `get_google_credentials()` | OAuth 2.0 authentication | N/A | `Credentials` object |
| `parse_relative_date()` | "tomorrow" → datetime | N/A | `tuple[datetime, datetime]` |
| `get_calendar_events()` | Query calendar availability | Calendar API | JSON array of events |
| `create_calendar_event()` | Book appointment + send confirmation email | Calendar + Gmail API | Success message string |

---

### Configuration Files

#### `.env` - Environment Variables
- API keys for Deepgram, OpenAI, Cartesia
- Optional: Google credentials/token paths
- **Not in version control**

#### `credentials.json` - Google OAuth Client Credentials
- Downloaded from Google Cloud Console
- Contains client ID, client secret, OAuth metadata
- **Not in version control**

#### `token.json` - Google OAuth Access Token
- Auto-generated after OAuth flow
- Contains access token, refresh token, expiration
- **Not in version control**

---

## Technical Architecture

### Voice AI Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ User Audio Input                                                │
└─────────────────┬───────────────────────────────────────────────┘
                  │
                  ▼
         ┌────────────────────┐
         │ Transport (WebRTC) │  ← Receives audio stream
         └────────┬───────────┘
                  │
                  ▼
         ┌────────────────────┐
         │ RTVI Processor     │  ← Real-Time Voice Interaction protocol
         └────────┬───────────┘
                  │
                  ▼
         ┌────────────────────┐
         │ STT Mute Filter    │  ← Mutes STT during function calls
         └────────┬───────────┘
                  │
                  ▼
         ┌────────────────────┐
         │ Deepgram STT       │  ← Speech → Text
         └────────┬───────────┘
                  │
                  ▼
         ┌────────────────────┐
         │ Context Aggregator │  ← Manages conversation history
         └────────┬───────────┘
                  │
                  ▼
         ┌────────────────────┐
         │ OpenAI LLM         │  ← Intent understanding + function calling
         └────────┬───────────┘
                  │
                  ├──── Function Call? ───┐
                  │                        │
                  │                        ▼
                  │              ┌─────────────────────┐
                  │              │ functions.py        │
                  │              │ - get_calendar      │
                  │              │ - create_event      │
                  │              └──────────┬──────────┘
                  │                         │
                  │                         ▼
                  │              ┌─────────────────────┐
                  │              │ Google APIs         │
                  │              │ - Calendar API      │
                  │              │ - Gmail API         │
                  │              └──────────┬──────────┘
                  │                         │
                  │                         │
                  │◄────── Result ──────────┘
                  │
                  ▼
         ┌────────────────────┐
         │ Cartesia TTS       │  ← Text → Speech
         └────────┬───────────┘
                  │
                  ▼
         ┌────────────────────┐
         │ Transport Output   │  ← Sends audio stream
         └────────┬───────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ User Audio Output                                               │
└─────────────────────────────────────────────────────────────────┘
```

### Function Calling Mechanism

**How LLM decides to call functions**:

1. **Tool definitions** in `bot.py` (lines 74-143) describe function schemas to OpenAI
2. **System prompt** (lines 151-184) instructs when to use each function
3. **LLM analyzes** user intent from conversation context
4. **LLM generates** function call with parameters
5. **Pipecat framework** routes call to registered Python function
6. **Function executes** and returns result
7. **LLM receives** result and generates natural language response

**Example - Booking Flow**:

```python
# User: "Book me for Monday at 2 PM"
# LLM detects missing info (name, email), asks questions first

# User: "John Smith"
# User: "john@example.com"

# LLM generates function call:
{
    "name": "create_calendar_event",
    "arguments": {
        "title": "Appointment with John Smith",
        "date_description": "monday",
        "start_time": "14:00",
        "customer_email": "john@example.com",
        "duration_minutes": 60
    }
}

# Pipecat routes to:
await create_calendar_event(params)

# Function creates calendar event + sends email
# Returns: "Event created successfully: 'Appointment with John Smith'..."

# LLM receives result, generates:
# "Your appointment is confirmed for Monday at 2 PM. You'll receive a confirmation email."
```

---

## Code Deep Dive

### bot.py - Tool Registration Pattern

```python
# 1. Define tool schema for OpenAI (lines 74-90)
calendar_tool_definition = {
    "type": "function",
    "function": {
        "name": "get_calendar_events",
        "description": "Check the tax advisor's calendar...",
        "parameters": { ... }
    }
}

# 2. Register Python function with LLM (line 147)
llm.register_function("get_calendar_events", get_calendar_events)

# 3. Add to LLM context (lines 187-190)
context = OpenAILLMContext(
    messages,
    tools=[calendar_tool_definition, gmail_tool_definition, ...]
)
```

### functions.py - Date Parsing Logic

**Natural language → datetime conversion** (lines 92-170):

```python
def parse_relative_date(date_description: str = "today"):
    # "tomorrow" → now + 1 day
    # "next monday" → calculates days_ahead based on weekday index
    # Returns (day_start, day_end) tuple for API queries

    # Example: "next monday"
    days_ahead = 0 - now.weekday()  # Monday = 0
    if days_ahead <= 0:
        days_ahead += 7  # Jump to next week
    target_date = now + timedelta(days=days_ahead)
```

### functions.py - Google Calendar Integration

**Timezone handling** (lines 251-284):

```python
# System gets local timezone offset
local_offset = datetime.now().astimezone().utcoffset()
offset_hours = int(local_offset.total_seconds() / 3600)

# Convert to Etc/GMT format (signs are reversed!)
# If local is UTC+2, we need Etc/GMT-2
if offset_hours >= 0:
    local_tz_str = f"Etc/GMT-{offset_hours}"
else:
    local_tz_str = f"Etc/GMT+{abs(offset_hours)}"

# Calendar event structure
event = {
    'summary': title,
    'start': {
        'dateTime': '2024-12-30T14:00:00',  # No timezone in string
        'timeZone': 'Etc/GMT-2'  # Timezone specified separately
    }
}
```

**Why this approach?** Google Calendar API requires timezone in `Etc/GMT` format with reversed signs, separate from the datetime string.

### bot.py - Current Date/Time Awareness

**Injecting current date into system prompt** (lines 157-171):

```python
# Get current date/time to inform the LLM
from datetime import datetime
current_datetime = datetime.now()
current_date_str = current_datetime.strftime("%A, %B %d, %Y")  # "Wednesday, December 25, 2025"
current_time_str = current_datetime.strftime("%I:%M %p")  # "02:30 PM"

# Add to system prompt
f"CURRENT DATE AND TIME:\n"
f"- Today is: {current_date_str}\n"
f"- Current time: {current_time_str}\n"
f"- Use this information when the client says 'today', 'tomorrow', etc.\n\n"
```

**Why this is important**: LLMs have a knowledge cutoff date and may not know the current date. By injecting the real-time date/time into the system prompt, the AI knows exactly what "today" means and can correctly interpret relative dates like "tomorrow" or "next Monday."

### functions.py - Past Appointment Prevention

**Filtering past time slots in `get_calendar_events()`** (lines 242-262):

```python
# Get current time for filtering past events
now = datetime.now()

for event in events:
    start_dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')).astimezone()

    # Skip events that have already started (only for today)
    # This prevents showing/booking appointments in the past
    if start_dt <= now:
        continue  # Don't show this event

    # Add to filtered results only if in the future
    filtered_events.append({...})
```

**Validating against past bookings in `create_calendar_event()`** (lines 367-373):

```python
# Validate that appointment is not in the past
now = datetime.now()
if event_start <= now:
    error_msg = f"Cannot book appointment in the past. The requested time {event_start.strftime('%I:%M %p')} has already passed. Please choose a future time slot."
    logger.error(f"❌ {error_msg}")
    await params.result_callback(error_msg)
    return error_msg  # LLM explains to user, suggests future times
```

**Why this is important**: Prevents customers from booking appointments at 1 PM when it's already 2 PM. Similar to preventing weekend bookings and after-hours appointments, this validation ensures only valid future time slots can be booked.

### functions.py - Email Sending

**Dual format emails** (lines 291-357):

```python
# Create MIME multipart message
message = MIMEMultipart('alternative')
message['To'] = customer_email
message['From'] = 'me'  # 'me' = authenticated user

# Attach both plain text and HTML
part1 = MIMEText(text_body, 'plain')
part2 = MIMEText(html_body, 'html')
message.attach(part1)
message.attach(part2)

# Base64 encode for Gmail API
raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

# Send via Gmail API
gmail_service.users().messages().send(
    userId='me',
    body={'raw': raw_message}
).execute()
```

---

## Google API Technical Details

### OAuth 2.0 Flow

```python
# 1. Check for existing token
if os.path.exists('token.json'):
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)

# 2. Refresh if expired
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())

# 3. New auth flow if needed
else:
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)  # Opens browser

    # Save for next time
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
```

### Calendar API - Event Query

```python
# Query events for a specific date range
events_result = service.events().list(
    calendarId='primary',
    timeMin='2024-12-30T00:00:00Z',  # UTC format required
    timeMax='2024-12-31T00:00:00Z',
    maxResults=50,
    singleEvents=True,  # Expand recurring events
    orderBy='startTime'
).execute()

# Filter to timed events only (exclude all-day events)
for event in events_result.get('items', []):
    if event.get('start', {}).get('dateTime'):  # Has specific time?
        # Process event...
```

---

## Pipecat Framework Patterns

### FunctionCallParams Pattern

All LLM-callable functions receive `FunctionCallParams`:

```python
async def my_function(params: FunctionCallParams):
    # Extract arguments from LLM call
    arg1 = params.arguments.get('arg1')

    # Push TTS frame for immediate user feedback
    await params.llm.push_frame(TTSSpeakFrame("Processing..."))

    # Do work...
    result = do_something(arg1)

    # Return result to LLM
    await params.result_callback(result)
    return result
```

### STT Mute Filter

**Purpose**: Prevents awkward silence during function execution

```python
# bot.py line 196
stt_mute_filter = STTMuteFilter(
    config=STTMuteConfig(
        strategies={STTMuteStrategy.FUNCTION_CALL}
    )
)
```

When LLM calls a function:
1. STT mute filter detects function call frame
2. Temporarily mutes speech-to-text
3. Function executes (calendar API calls, etc.)
4. Function completes
5. STT unmutes
6. User can speak again

**Why?** Without this, user might speak during function execution, causing interruptions.

---

## Data Structures

### Calendar Event (from Google API)
```json
{
  "summary": "Appointment with John Smith",
  "start": {
    "dateTime": "2024-12-30T14:00:00",
    "timeZone": "Etc/GMT-2"
  },
  "end": {
    "dateTime": "2024-12-30T15:00:00",
    "timeZone": "Etc/GMT-2"
  }
}
```

### Filtered Event (to LLM)
```json
{
  "summary": "Appointment with John Smith",
  "start_time": "02:00 PM",
  "end_time": "03:00 PM"
}
```

---

## Extending the System

### Adding a New Function Tool

**1. Implement function in `functions.py`:**

```python
async def new_function(params: FunctionCallParams):
    """Docstring explaining purpose."""
    # Extract arguments
    arg = params.arguments.get('arg_name')

    # Immediate TTS feedback
    await params.llm.push_frame(TTSSpeakFrame("Processing..."))

    # Execute logic
    result = your_api_call(arg)

    # Return to LLM
    await params.result_callback(result)
    return result
```

**2. Register in `bot.py`:**

```python
# Import function
from functions import new_function

# Register with LLM (in run_bot function)
llm.register_function("new_function", new_function)
```

**3. Define tool schema in `bot.py`:**

```python
new_tool_definition = {
    "type": "function",
    "function": {
        "name": "new_function",
        "description": "Clear description for LLM decision-making",
        "parameters": {
            "type": "object",
            "properties": {
                "arg_name": {
                    "type": "string",
                    "description": "What this argument represents"
                }
            },
            "required": ["arg_name"]
        }
    }
}
```

**4. Add to context:**

```python
context = OpenAILLMContext(
    messages,
    tools=[calendar_tool_definition, gmail_tool_definition, new_tool_definition]
)
```

**5. Update system prompt** to tell LLM when to use it.

---

## Performance Considerations

### VAD (Voice Activity Detection) Parameters

```python
# bot.py lines 245-246, 251-252
vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2))
```

- `stop_secs=0.2`: Wait 0.2 seconds of silence before considering user finished speaking
- **Lower value**: More responsive, may cut off user mid-sentence
- **Higher value**: More accurate, but slower response time

### Turn Analysis

```python
turn_analyzer=LocalSmartTurnAnalyzerV3()
```

Analyzes conversation patterns to determine when to let user speak vs. bot speak. Version 3 is latest model with improved accuracy.

---

## Error Handling Patterns

All functions in `functions.py` follow this pattern:

```python
async def function_name(params: FunctionCallParams):
    try:
        # Function logic
        result = do_work()
        await params.result_callback(result)
        return result

    except Exception as e:
        logger.error(f"❌ Failed to ...: {e}")
        error_result = f"Error: {str(e)}"
        await params.result_callback(error_result)
        return error_result  # LLM receives error, explains to user gracefully
```

**Why this approach?**
- Errors are returned to LLM, not raised
- LLM can explain errors naturally: "Sorry, I couldn't access the calendar right now."
- User experience remains smooth even during failures

---

## Logging

Uses Loguru with emojis for visual scanning:

```python
logger.info("📅 Fetching calendar events...")  # Calendar operations
logger.info("📧 Sending confirmation email...") # Email operations
logger.info("✅ Success message")              # Successes
logger.error("❌ Error message")               # Errors
```

---

## Summary: Quick Developer Reference

| Task | File | Location |
|------|------|----------|
| Modify AI personality/rules | `bot.py` | System prompt (lines 152-183) |
| Add new function capability | `functions.py` + `bot.py` | Implement function, register, add schema |
| Change calendar query logic | `functions.py` | `get_calendar_events()` (lines 173-243) |
| Modify appointment creation | `functions.py` | `create_calendar_event()` (lines 280-419) |
| Update email template | `functions.py` | Email body generation (lines 304-341) |
| Adjust VAD sensitivity | `bot.py` | VADParams (lines 245, 251) |
| Change pipeline order | `bot.py` | Pipeline definition (lines 199-211) |
| Add new AI service | `bot.py` | Import, instantiate, add to pipeline |

---

**Developer Notes**:
- All async operations use `await`
- Google API calls are synchronous (wrapped in async functions)
- TTS feedback via `params.llm.push_frame(TTSSpeakFrame(...))` happens immediately before API calls
- Function results are JSON strings for LLM parsing
