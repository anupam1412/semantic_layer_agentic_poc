import traceback

from agent import root_agent

print("root_agent type:", type(root_agent))

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
print("callable methods (filtered):")
for name in sorted(callables):
    if any(k in name.lower() for k in keywords):
        print(" -", name)
print("total callable methods:", len(callables))

# Try to execute with common method names
for method in ["run", "execute", "call", "process", "start", "respond"]:
    if hasattr(root_agent, method):
        print(f"\n--- attempting {method}() ---")
        try:
            func = getattr(root_agent, method)
            if callable(func):
                result = func("Test question: What was revenue last month?")
                print("result:", result)
                break
        except Exception as e:
            print("error calling", method, type(e), e)
            traceback.print_exc()
