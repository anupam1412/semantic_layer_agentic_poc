import pkgutil
import google.adk.sessions as sessions

print('google.adk.sessions modules:')
for mod in pkgutil.iter_modules(sessions.__path__):
    print('-', mod.name)

# Inspect key classes in sessions
import inspect
from google.adk.sessions import base_session_service
print('\nbase_session_service members:')
for name in dir(base_session_service):
    if name.islower() and 'session' in name:
        print(' -', name)

try:
    from google.adk.sessions import local_session_service
    print('\nlocal_session_service members:')
    for name in dir(local_session_service):
        if 'Session' in name or 'Service' in name:
            print(' -', name)
except ImportError:
    print('local_session_service not available')
