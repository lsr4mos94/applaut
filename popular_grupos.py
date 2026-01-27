import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')
django.setup()

from django.contrib.auth.models import Group

grupos = ['Vendedor', 'Gestor', 'BackOffice']

for nome in grupos:
    novo_grupo, criado = Group.objects.get_or_create(name=nome)
    if criado:
        print(f"Grupo {nome} criado com sucesso!")
    else:
        print(f"Grupo {nome} já existe.")