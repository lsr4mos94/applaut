import os
import sys

# Define o caminho para o diretório raiz do projeto Django (salesapp)
# Isso garante que Python possa encontrar 'salesapp.wsgi'
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.append(project_root)

# Agora sim, você pode importar 'salesapp.wsgi'
from waitress import serve
from salesapp.wsgi import application # Certifique-se de que 'salesapp' é o nome correto do seu app/diretório

if __name__ == '__main__':
    # Altere o host e a porta conforme necessário
    print(f"Waitress serving on http://192.168.184.24:8000 from {project_root}")
    serve(application, host='0.0.0.0', port=8000)