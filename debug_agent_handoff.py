"""
Debug script to trace ADK agent handoffs and identify stall points.
Run this to diagnose where the pipeline gets stuck.

Usage:
    python debug_agent_handoff.py "What was our total revenue last month?"
"""

import sys
import os
import asyncio
import logging
from datetime import datetime

# Add project to path
project_path = r"C:\Users\anupam.jha\OneDrive - Accenture\Documents\GitHub\semantic_layer_agentic_poc"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

# Also add parent for package discovery
parent_path = os.path.dirname(project_path)
if parent_path not in sys.path:
    sys.path.insert(0, parent_path)

# Set logging level - use INFO to reduce noise, DEBUG for full trace
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Suppress noisy loggers
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("google.auth").setLevel(logging.WARNING)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import Event

# Import your root agent
try:
    from semantic_layer_agentic_poc.agent import root_agent
except ImportError:
    from agent import root_agent


async def trace_agent_execution(question: str, timeout_seconds: int = 300):
    """Run a question through the agent pipeline with detailed tracing."""
    
    print(f"\n{'='*70}")
    print(f"DIAGNOSTIC TRACE - {datetime.now().strftime('%H:%M:%S')}")
    print(f"Question: {question}")
    print(f"Timeout: {timeout_seconds}s")
    print(f"{'='*70}\n")
    
    # Create session service and runner
    session_service = InMemorySessionService()
    
    runner = Runner(
        agent=root_agent,
        app_name="debug_trace",
        session_service=session_service,
    )
    
    # Create a session
    session = await session_service.create_session(
        app_name="debug_trace",
        user_id="debug_user",
    )
    
    # Track events
    event_count = 0
    agent_sequence = []  # Ordered list of agents seen
    tool_calls = []
    transfers = []
    errors = []
    final_response = None
    
    print("[STARTING PIPELINE]\n")
    start_time = datetime.now()
    
    # Create user content
    from google.genai import types
    user_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=question)]
    )
    
    try:
        async for event in runner.run_async(
            user_id="debug_user",
            session_id=session.id,
            new_message=user_content,
        ):
            event_count += 1
            event_time = (datetime.now() - start_time).total_seconds()
            
            # Check timeout
            if event_time > timeout_seconds:
                print(f"\n[TIMEOUT] Exceeded {timeout_seconds}s limit")
                break
            
            # Get author (which agent produced this event)
            author = getattr(event, 'author', None)
            
            # Track agent sequence
            if author and (not agent_sequence or agent_sequence[-1] != author):
                agent_sequence.append(author)
                print(f"[{event_time:6.1f}s] 🔄 AGENT: {author}")
            
            # Check for transfer_to_agent function calls
            actions = getattr(event, 'actions', None)
            if actions:
                function_calls = getattr(actions, 'function_calls', None) or []
                for fc in function_calls:
                    func_name = getattr(fc, 'name', '')
                    func_args = getattr(fc, 'args', {})
                    
                    if func_name == 'transfer_to_agent':
                        target = func_args.get('agent_name', 'unknown')
                        transfers.append({
                            'from': author,
                            'to': target,
                            'time': event_time
                        })
                        print(f"[{event_time:6.1f}s]    ↳ TRANSFER: {author} → {target}")
                    else:
                        tool_calls.append({
                            'tool': func_name,
                            'agent': author,
                            'time': event_time
                        })
                        print(f"[{event_time:6.1f}s]    ↳ TOOL: {func_name}")
            
            # Check for text content (responses)
            content = getattr(event, 'content', None)
            if content and hasattr(content, 'parts'):
                for part in content.parts:
                    text = getattr(part, 'text', None)
                    if text and len(text.strip()) > 0:
                        # Show preview of text
                        preview = text[:100].replace('\n', ' ').strip()
                        if len(text) > 100:
                            preview += "..."
                        print(f"[{event_time:6.1f}s]    ↳ TEXT: {preview}")
            
            # Check for errors
            error = getattr(event, 'error_message', None) or getattr(event, 'error', None)
            if error:
                errors.append({
                    'error': str(error),
                    'agent': author,
                    'time': event_time
                })
                print(f"[{event_time:6.1f}s]    ⚠️ ERROR: {error}")
            
            # Check for final response - but DON'T break on transfer events
            is_final = getattr(event, 'is_final_response', False)
            turn_complete = getattr(event, 'turn_complete', False)
            
            # Only treat as final if it's actually a final response with content
            # AND not just a transfer
            if (is_final or turn_complete):
                # Check if this is a real final response (has text content, not just a transfer)
                has_real_content = False
                if content and hasattr(content, 'parts'):
                    for part in content.parts:
                        text = getattr(part, 'text', None)
                        if text and len(text.strip()) > 50:  # Substantial text
                            has_real_content = True
                            final_response = text
                            break
                
                if has_real_content:
                    print(f"\n[{event_time:6.1f}s] ✅ FINAL RESPONSE RECEIVED")
                    break
                    
    except asyncio.TimeoutError:
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n[TIMEOUT] Pipeline timed out after {elapsed:.1f}s")
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n[EXCEPTION] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        errors.append({'error': str(e), 'time': elapsed, 'agent': 'unknown'})
    
    # Summary
    total_time = (datetime.now() - start_time).total_seconds()
    
    print(f"\n{'='*70}")
    print("DIAGNOSTIC SUMMARY")
    print(f"{'='*70}")
    print(f"Total time: {total_time:.1f}s")
    print(f"Events processed: {event_count}")
    
    # Expected agent chain
    expected_chain = [
        'OrchestratorAgent', 
        'TriageAgent', 
        'PlannerAgent', 
        'InvestigatorAgent', 
        'SchemaAgent', 
        'ExecutorAgent', 
        'AnalysisAgent', 
        'SynthesisAgent', 
        'LearningAgent'
    ]
    
    print(f"\nAgent sequence ({len(agent_sequence)} agents):")
    for i, agent in enumerate(agent_sequence):
        status = "✓" if agent in expected_chain else "?"
        print(f"  {i+1}. {agent} {status}")
    
    print(f"\nTransfers ({len(transfers)}):")
    for t in transfers:
        print(f"  • {t['from']} → {t['to']} (t={t['time']:.1f}s)")
    
    print(f"\nTool calls ({len(tool_calls)}):")
    for tc in tool_calls:
        print(f"  • {tc['tool']} by {tc['agent']} (t={tc['time']:.1f}s)")
    
    if errors:
        print(f"\n⚠️ Errors ({len(errors)}):")
        for err in errors:
            print(f"  • [{err.get('agent', '?')}] {err['error'][:100]}")
    
    # Diagnose stalls
    if agent_sequence:
        last_agent = agent_sequence[-1]
        
        # Find expected next agent
        if last_agent in expected_chain:
            idx = expected_chain.index(last_agent)
            if idx < len(expected_chain) - 1:
                expected_next = expected_chain[idx + 1]
                
                # Check if we reached the expected agents
                if 'SynthesisAgent' not in agent_sequence and 'LearningAgent' not in agent_sequence:
                    print(f"\n⚠️  POTENTIAL STALL: Last agent was {last_agent}")
                    print(f"   Expected to continue to: {expected_next}")
                    
                    if last_agent == 'PlannerAgent':
                        print("\n   DIAGNOSIS: Planner → Investigator handoff may have failed")
                        print("   Check if the Planner's output format is triggering delegation")
                    elif last_agent == 'TriageAgent':
                        print("\n   DIAGNOSIS: Triage → Planner handoff may have failed")
                        print("   Check if triage returned NOT_ANSWERABLE")
    
    if final_response:
        print(f"\n📝 Final Response Preview:")
        print(f"   {final_response[:200]}...")
    
    return {
        'agents': agent_sequence,
        'transfers': transfers,
        'tools': tool_calls,
        'errors': errors,
        'total_time': total_time,
        'final_response': final_response
    }


if __name__ == "__main__":
    question = sys.argv[1] if len(sys.argv) > 1 else "What was our total revenue last month?"
    
    # Optional timeout as second argument
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    
    result = asyncio.run(trace_agent_execution(question, timeout))
    
    # Exit with error code if we didn't complete the chain
    if 'SynthesisAgent' not in result['agents']:
        sys.exit(1)