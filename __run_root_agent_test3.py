import asyncio
import inspect

from agent import root_agent

print("run_async signature:", inspect.signature(root_agent.run_async))
print("run_live signature:", inspect.signature(root_agent.run_live))

async def main():
    q = "Test question: What was revenue last month?"
    print("Starting async run...")
    async for event in root_agent.run_async(q):
        print("EVENT:", event)
    print("Async run complete")

asyncio.run(main())
