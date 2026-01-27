import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
time.sleep(0.1)

from django.core.wsgi import get_wsgi_application

time.sleep(0.1)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')

time.sleep(0.1)

try:
    application = get_wsgi_application()
    time.sleep(0.1)
except Exception as e:
    import traceback
    traceback.print_exc()
    time.sleep(0.5)
    raise

time.sleep(0.1)