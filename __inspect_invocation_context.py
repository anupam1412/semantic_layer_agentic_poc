import inspect

from google.adk.agents import InvocationContext

print('InvocationContext class:', InvocationContext)
print('signature:', inspect.signature(InvocationContext))
print('\nClass methods (filtered):')
for name in dir(InvocationContext):
    if name.startswith('_'):
        continue
    if 'from' in name.lower() or 'create' in name.lower() or 'build' in name.lower():
        print(' -', name)
