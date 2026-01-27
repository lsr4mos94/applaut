import os
import sys
import time
import traceback


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

# 2. CONFIGURAÇÃO DO DJANGO
# Define qual arquivo de configurações o Django deve usar
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')

# 3. CARREGAMENTO DA APLICAÇÃO (WSGI)
try:
    print("--- Iniciando Boot do Servidor Waitress ---")
    from django.core.wsgi import get_wsgi_application
    
    # Pequena pausa para garantir que o sistema de arquivos liberou os módulos (comum em Windows Service)
    time.sleep(0.2)
    
    application = get_wsgi_application()
    print("Sucesso: Aplicação WSGI carregada.")
    
except Exception as e:
    print("\n[ERRO CRÍTICO AO CARREGAR WSGI]")
    traceback.print_exc()
    # Mantém o console aberto por alguns segundos em caso de erro para leitura no log do serviço
    time.sleep(10)
    sys.exit(1)

# 4. EXECUÇÃO PELO WAITRESS
if __name__ == '__main__':
    from waitress import serve
    
    # Configurações do servidor
    HOST = '0.0.0.0'  # Escuta em todos os IPs da máquina
    PORT = 8000
    IP_SISTEMA = '192.168.184.24' # Seu IP de rede
    
    print(f"\nServidor Online: http://{IP_SISTEMA}:{PORT}")
    print(f"Diretório Raiz: {BASE_DIR}")
    print("Apps Ativos: usuarios, cadastros, solicitacoes, app (core)")
    print("Pressione Ctrl+C para encerrar (se rodando manualmente)\n")

    # Parâmetros de produção
    serve(
        application, 
        host=HOST, 
        port=PORT, 
        threads=10,                # Aumentado para lidar com os 4 apps simultâneos
        channel_timeout=120,       # Tempo de espera para consultas longas no PostgreSQL
        max_request_body_size=1073741824, # Limite de 1GB para requisições
        url_scheme='http'
    )