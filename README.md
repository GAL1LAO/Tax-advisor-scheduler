# Tax Advisor Appointment Scheduler Bot

An AI-powered voice scheduling assistant that helps clients book appointments with a tax advisor. The bot features real-time video avatars, calendar integration, and automated email confirmations.

## Features

### Core Capabilities

- **Voice Interaction**: Natural conversation using Deepgram STT and Cartesia sonic-3 TTS
- **Video Avatar**: Real-time AI video generation powered by Tavus
- **Smart Scheduling**: Natural language date parsing (today, tomorrow, next Monday, etc.)
- **Calendar Integration**: Direct Google Calendar integration for checking availability and booking appointments
- **Email Confirmations**: Automatic HTML email confirmations sent to clients via Gmail
- **Business Rules**: Enforces weekday-only appointments (Mon-Fri) during business hours (09:00-17:00)

### Assistant Capabilities

The AI assistant "Sarah" can:

1. **Check Availability**: Query the tax advisor's calendar for specific days using natural language
2. **Book Appointments**: Create calendar events with client details and automatically send confirmation emails
3. **Validate Requests**: Reject weekend appointments and out-of-hours bookings with helpful suggestions
4. **Collect Information**: Gather client name, preferred date/time, and email address
5. **Confirm Details**: Review appointment details before finalizing the booking

## Prerequisites

### Environment

- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager installed

### Required API Keys

You'll need API keys from the following services:

- [Deepgram](https://console.deepgram.com/signup) - Speech-to-Text
- [OpenAI](https://auth.openai.com/create-account) - LLM inference (GPT-4)
- [Cartesia](https://play.cartesia.ai/sign-up) - Text-to-Speech (sonic-3 model)
- [Tavus](https://tavus.io) - AI video avatar generation

### Google Cloud Setup

For calendar and email functionality:

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the following APIs:
   - Google Calendar API
   - Gmail API
3. Create OAuth 2.0 credentials (Desktop application)
4. Download the credentials file as `credentials.json`
5. Place `credentials.json` in the project root directory

## Setup

1. Clone this repository

   ```bash
   git clone https://github.com/GAL1LAO/Tax-advisor-scheduler.git
   cd Tax-advisor-scheduler
   ```

2. Install dependencies

   ```bash
   uv sync
   ```

3. Install additional required packages

   ```bash
   uv add google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib
   uv add "pipecat-ai[tavus]"
   ```

4. Configure your API keys

   Create a `.env` file:

   ```bash
   touch .env
   ```

   Add your API keys:

   ```ini
   DEEPGRAM_API_KEY=your_deepgram_api_key
   OPENAI_API_KEY=your_openai_api_key
   CARTESIA_API_KEY=your_cartesia_api_key
   TAVUS_API_KEY=your_tavus_api_key
   TAVUS_REPLICA_ID=your_tavus_replica_id
   ```

5. Set up Google OAuth

   On first run, the bot will open a browser window for Google OAuth authentication. Grant access to:
   - Google Calendar (read/write)
   - Gmail (send emails)

   The authentication token will be saved as `token.json` for future use.

## Run the Bot

```bash
uv run bot.py
```

**Open http://localhost:7860 in your browser** and click `Connect` to start interacting with the scheduling assistant.

> 💡 **First run note**: Initial startup takes ~20 seconds as Pipecat downloads required models. Google OAuth authentication will also launch in your browser on first run.

## Usage Examples

Once connected, you can interact with Sarah, the scheduling assistant:

- **Check availability**: "What's the advisor's schedule for tomorrow?"
- **Book appointment**: "I'd like to book an appointment for next Monday at 2 PM"
- **Get recent emails**: "Can you check my recent emails?"

The bot will:
1. Greet you professionally
2. Check calendar availability for your requested time
3. Collect your name and email address
4. Confirm the appointment details
5. Create the calendar event
6. Send an HTML confirmation email to your address

## File Structure

- `bot.py` - Main bot configuration with pipeline setup and AI assistant prompt
- `functions.py` - Calendar and Gmail integration functions
- `credentials.json` - Google OAuth credentials (not in version control)
- `token.json` - Google OAuth token (auto-generated, not in version control)
- `.env` - API keys (not in version control)

## Business Hours

The bot enforces the following rules:
- **Weekdays only**: Monday through Friday
- **Business hours**: 09:00 to 17:00 (9 AM to 5 PM)
- **Default duration**: 60 minutes (1 hour)

Weekend requests and out-of-hours appointments are politely rejected with alternative suggestions.

## Tech Stack

- **Pipecat**: Voice AI pipeline framework
- **Deepgram**: Real-time speech-to-text
- **OpenAI GPT-4**: Natural language understanding and function calling
- **Cartesia sonic-3**: High-quality text-to-speech
- **Tavus**: Real-time AI video avatar generation
- **Google Calendar API**: Appointment scheduling
- **Gmail API**: Email confirmations
