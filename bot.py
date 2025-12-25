#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Pipecat Quickstart Example.

The example runs a simple voice AI bot that you can connect to using your
browser and speak with it. You can also deploy this bot to Pipecat Cloud.

Required AI services:
- Deepgram (Speech-to-Text)
- OpenAI (LLM)
- Cartesia (Text-to-Speech)

Run the bot using::

    uv run bot.py
"""

import os

from dotenv import load_dotenv
from loguru import logger

print("🚀 Starting Pipecat bot...")
print("⏳ Loading models and imports (20 seconds, first run only)\n")

logger.info("Loading Local Smart Turn Analyzer V3...")
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

logger.info("✅ Local Smart Turn Analyzer V3 loaded")
logger.info("Loading Silero VAD model...")
from pipecat.audio.vad.silero import SileroVADAnalyzer

logger.info("✅ Silero VAD model loaded")

from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame, StartFrame

logger.info("Loading pipeline components...")
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.filters.stt_mute_filter import STTMuteConfig, STTMuteFilter, STTMuteStrategy
from pipecat.processors.frameworks.rtvi import RTVIConfig, RTVIObserver, RTVIProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams

logger.info("✅ All components loaded successfully!")

load_dotenv(override=True)

from functions import get_calendar_events, get_gmail_emails, create_calendar_event

async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info(f"Starting bot")
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
    
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        model_id="sonic-3",
        voice_id="f786b574-daa5-4673-aa0c-cbe3e8534c02",  # British Reading Lady
    )

    # Define the Calendar function schema for the LLM
    calendar_tool_definition = {
        "type": "function",
        "function": {
            "name": "get_calendar_events",
            "description": "Check the tax advisor's calendar to see existing appointments and find available time slots for a specified day. Use this when clients ask about availability or want to see open slots on a particular day (today, tomorrow, specific weekdays).",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_description": {
                        "type": "string",
                        "description": "Natural language description of the date (e.g., 'today', 'tomorrow', 'monday', 'next friday'). Only use weekdays (Monday-Friday), not weekends.",
                    }
                },
                "required": [],
            },
        },
    }

    # Define the Gmail function schema for the LLM
    gmail_tool_definition = {
        "type": "function",
        "function": {
            "name": "get_gmail_emails",
            "description": "Get the 2 most recent Gmail emails. Use this when the user asks about their emails, messages, or wants to check their inbox.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }

    # Define the Create Calendar Event function schema for the LLM
    create_event_tool_definition = {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Book an appointment for a client with the tax advisor. Use this after confirming the client's name, preferred date, and time. ONLY book appointments on weekdays (Monday-Friday) between 09:00-17:00.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The appointment title including client's name (e.g., 'Appointment with John Smith', 'Client Meeting - Maria Garcia')",
                    },
                    "date_description": {
                        "type": "string",
                        "description": "Natural language date description for weekdays only (e.g., 'today', 'tomorrow', 'monday', 'next friday'). DO NOT use 'saturday' or 'sunday'.",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time in 24-hour format HH:MM between 09:00 and 17:00 (e.g., '14:00' for 2 PM, '09:30' for 9:30 AM). Must be within business hours.",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duration of the appointment in minutes (default: 60 for standard 1-hour appointment)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional notes about the appointment (e.g., 'Tax consultation', 'Annual tax return review')",
                    },
                    "customer_email": {
                        "type": "string",
                        "description": "Customer's email address to send appointment confirmation (e.g., 'client@example.com')",
                    }
                },
                "required": ["title", "date_description", "start_time", "customer_email"],
            },
        },
    }

    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))

    llm.register_function("get_calendar_events", get_calendar_events)
    llm.register_function("get_gmail_emails", get_gmail_emails)
    llm.register_function("create_calendar_event", create_calendar_event)

    messages = [
        {
            "role": "system",
            "content": (
                "You are an AI scheduling assistant for a tax advisor's office. Your name is Sarah, and you help clients book appointments with the tax advisor.\n\n"
                "BUSINESS HOURS AND RULES:\n"
                "- Appointments are only available Monday through Friday (weekdays only, NO weekends)\n"
                "- Business hours: 09:00 to 17:00 (9 AM to 5 PM)\n"
                "- Default appointment duration: 60 minutes (1 hour)\n"
                "- You represent the tax advisor when speaking with clients\n\n"
                "Your capabilities:\n"
                "1. Check the tax advisor's availability using 'get_calendar_events' function. "
                "When a client asks about available time slots, check the calendar for the requested day (today, tomorrow, specific weekdays) to see existing appointments.\n"
                "2. Book appointments using 'create_calendar_event' function. The event title should include the client's name (e.g., 'Appointment with [Client Name]'). "
                "IMPORTANT VALIDATIONS before booking:\n"
                "   - Only accept appointments Monday-Friday (reject weekend requests politely)\n"
                "   - Only accept times between 09:00-17:00 (reject times outside business hours)\n"
                "   - Convert client's time to 24-hour format (e.g., '2 PM' becomes '14:00')\n"
                "   - Suggest alternative weekday slots if the client requests a weekend\n\n"
                "WORKFLOW for booking appointments:\n"
                "1. Greet the client professionally\n"
                "2. Ask for their preferred day and time\n"
                "3. If they request a weekend, politely explain you only book weekdays and suggest Monday or Friday\n"
                "4. If they request time outside 09:00-17:00, explain business hours and suggest available times\n"
                "5. Check the calendar for the requested day to verify availability\n"
                "6. If the time slot is free, ask for the client's name\n"
                "7. Ask for the client's email address to send the appointment confirmation\n"
                "8. Confirm the appointment details (name, date, time, email) before booking\n"
                "9. Book the appointment - this will create the calendar event AND send a confirmation email to the client\n"
                "10. Inform the client that the appointment is confirmed and they will receive a confirmation email\n\n"
                "Be professional, courteous, and efficient. Keep responses concise and helpful. "
                "When greeting clients, say: 'Good morning/afternoon! I'm Sarah, the scheduling assistant for our tax advisory office. How may I help you schedule an appointment today?'"
            ),
        },
    ]

    context = OpenAILLMContext(
        messages,
        tools=[calendar_tool_definition, gmail_tool_definition, create_event_tool_definition]
    )
    context_aggregator = llm.create_context_aggregator(context)

    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    # Configure STT mute filter to mute during function calls (prevents awkward silence)
    stt_mute_filter = STTMuteFilter(config=STTMuteConfig(strategies={STTMuteStrategy.FUNCTION_CALL}))

    # Pipeline: Cartesia audio + Tavus video lip-sync
    pipeline = Pipeline(
        [
            transport.input(),  # Transport user input
            rtvi,  # RTVI processor
            stt_mute_filter,  # STT mute filter
            stt,
            context_aggregator.user(),  # User responses
            llm,  # LLM
            tts,  # Cartesia generates audio
            transport.output(),  # Transport bot output
            context_aggregator.assistant(),  # Assistant spoken responses
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[RTVIObserver(rtvi)],
    )
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected")
        # Kick off the conversation.
        messages.append({"role": "system", "content": "Say hello and briefly introduce yourself."})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point for the bot starter."""

    transport_params = {
        "daily": lambda: DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            turn_analyzer=LocalSmartTurnAnalyzerV3(),
        ),
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            turn_analyzer=LocalSmartTurnAnalyzerV3(),
        ),
    }

    transport = await create_transport(runner_args, transport_params)

    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
