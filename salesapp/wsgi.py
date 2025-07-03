import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
print(f"--- DEBUG WSGI: BASE_DIR adicionado ao sys.path: {BASE_DIR} ---", flush=True)
time.sleep(0.1)

from django.core.wsgi import get_wsgi_application

print("--- DEBUG WSGI: django.core.wsgi importado. ---", flush=True)
time.sleep(0.1)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'salesapp.settings')

print(f"--- DEBUG WSGI: DJANGO_SETTINGS_MODULE definido para: {os.environ.get('DJANGO_SETTINGS_MODULE')} ---", flush=True)
time.sleep(0.1)

try:
    application = get_wsgi_application()
    print("--- DEBUG WSGI: Aplicação WSGI Django obtida com sucesso! ---", flush=True)
    time.sleep(0.1)
except Exception as e:
    print(f"--- ERRO WSGI FINAL: Falha ao obter a aplicação WSGI: {e} ---", flush=True)
    import traceback
    traceback.print_exc()
    time.sleep(0.5)
    raise

print("--- DEBUG WSGI: wsgi.py script finished execution. ---", flush=True)
time.sleep(0.1)