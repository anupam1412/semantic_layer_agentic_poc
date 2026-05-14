import traceback
import time

from agent import root_agent

print("START: root_agent type:", type(root_agent), flush=True)

# Safely list callable methods
callables = []
for name in dir(root_agent):
    if name.startswith("_"):
        continue
    try:
        attr = getattr(root_agent, name)
    except Exception:
        continue
    if callable(attr):
        callables.append(name)

keywords = ["run", "execute", "call", "respond", "process", "start"]
print("callable methods (filtered):", flush=True)
for name in sorted(callables):
    if any(k in name.lower() for k in keywords):
        print(" -", name, flush=True)
print("total callable methods:", len(callables), flush=True)

# Try to execute with common method names
for method in ["run", "execute", "call", "process", "start", "respond", "run_async", "run_live"]:
    if hasattr(root_agent, method):
        print(f"\n--- attempting {method}() ---", flush=True)
        try:
            func = getattr(root_agent, method)
            if callable(func):
                start = time.time()
                result = func("Test question: What was revenue last month?")
                duration = time.time() - start
                print("result (type):", type(result), "duration:", duration, flush=True)
                print("result repr:\n", repr(result), flush=True)
                break
        except Exception as e:
            print("error calling", method, type(e), e, flush=True)
            traceback.print_exc()
