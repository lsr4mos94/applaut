import os
import sys
import time
import traceback


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')

try:
    print("--- Iniciando Boot do Servidor Waitress ---")
    from django.core.wsgi import get_wsgi_application
    
    time.sleep(0.2)
    
    application = get_wsgi_application()
    print("Sucesso: Aplicação WSGI carregada.")
    
except Exception as e:
    print("\n[ERRO CRÍTICO AO CARREGAR WSGI]")
    traceback.print_exc()
    time.sleep(10)
    sys.exit(1)

if __name__ == '__main__':
    from waitress import serve
    
    HOST = '0.0.0.0'
    PORT = 8000
    IP_SISTEMA = '192.168.184.24'
    
    print(f"\nServidor Online: http://{IP_SISTEMA}:{PORT}")
    print(f"Diretório Raiz: {BASE_DIR}")
    print("Apps Ativos: usuarios, cadastros, solicitacoes, app (core)")
    print("Pressione Ctrl+C para encerrar (se rodando manualmente)\n")

    serve(
        application, 
        host=HOST, 
        port=PORT, 
        threads=10,
        channel_timeout=120,
        max_request_body_size=1073741824,
        url_scheme='http'
    )