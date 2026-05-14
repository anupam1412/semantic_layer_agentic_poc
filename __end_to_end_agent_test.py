import asyncio

from agent import root_agent
from google.adk.sessions import in_memory_session_service, session
from google.adk.agents import InvocationContext
import uuid
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s - %(message)s")

async def run_question(question: str):
    """Run a single question through the semantic layer agent pipeline."""
    try:
        # Create session service and session
        session_service = in_memory_session_service.InMemorySessionService()
        s = session.Session(
            id=str(uuid.uuid4()),
            user_id="test_user",
            metadata={"test": True}
        )
        
        # Create invocation context
        ctx = InvocationContext(
            session_service=session_service,
            invocation_id=str(uuid.uuid4()),
            agent=root_agent,
            session=s,
        )
        
        print(f"\n{'='*60}")
        print(f"Running question: {question}")
        print(f"{'='*60}\n")
        
        # Run the agent asynchronously and collect events
        event_count = 0
        last_response = None
        
        async for event in root_agent.run_async(ctx):
            event_count += 1
            # Print event type
            if hasattr(event, 'type'):
                print(f"[Event {event_count}] Type: {event.type}")
            else:
                print(f"[Event {event_count}] {type(event).__name__}")
            
            # Capture response/final content
            if hasattr(event, 'content'):
                print(f"  Content: {str(event.content)[:200]}")
                last_response = event.content
            elif hasattr(event, 'message'):
                print(f"  Message: {str(event.message)[:200]}")
                last_response = event.message
            elif hasattr(event, 'text'):
                print(f"  Text: {str(event.text)[:200]}")
                last_response = event.text
        
        print(f"\n{'='*60}")
        print(f"Agent completed ({event_count} events)")
        print(f"Last response: {str(last_response)[:200] if last_response else 'None'}")
        print(f"{'='*60}\n")
        
    except Exception as e:
        import traceback
        print(f"\nERROR: {type(e).__name__}: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_question("What was the revenue trend last 3 months?"))
