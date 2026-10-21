"""
Regras de permissão por grupo, usadas nas views.

Os grupos são os mesmos que já controlam o menu e os botões das telas;
aqui a mesma regra passa a valer também no servidor.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect

# Quem pode o quê
GESTAO_COMERCIAL = ('Gestão Comercial',)            # aprovar/reprovar/excluir bonificação, verbas mensais, exportar
FATURAMENTO = ('Faturamento',)                      # concluir bonificação (pedido Protheus)
GESTAO_FINANCEIRA = ('Gestão Financeira',)          # aprovar/reprovar/excluir/exportar verba administrativa
CONTAS_A_PAGAR = ('Contas a Pagar',)                # concluir verba administrativa
PLANTAO_EQUIPE = ('Plantao', 'Gestão Financeira', 'Contas a Receber')  # confirmar plantão
PLANTAO_ACESSO = ('Vendedores',) + PLANTAO_EQUIPE   # ver a tela de plantões


def no_grupo(user, *grupos):
    """True se o usuário é superusuário ou pertence a algum dos grupos."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=grupos).exists()


def eh_somente_vendedor(user):
    """Vendedor sem nenhum grupo de gestão: só enxerga o que é dele."""
    if user.is_superuser:
        return False
    nomes = set(user.groups.values_list('name', flat=True))
    return 'Vendedores' in nomes and nomes == {'Vendedores'}


def pode_ver_bonificacao(user, bonificacao):
    return bonificacao.vendedor_id == user.id or not eh_somente_vendedor(user)


def pode_ver_cadastro(user, cadastro):
    return cadastro.vendedor_id == user.id or no_grupo(user, 'Cadastro', 'Contas a Receber', 'Gestão Comercial')


def pode_ver_verba_mensal(user, verba):
    return verba.vendedor_id == user.id or no_grupo(user, *GESTAO_COMERCIAL)


def pode_ver_acordo(user, acordo):
    return acordo.usuario_cadastro_id == user.id or no_grupo(user, *GESTAO_COMERCIAL)


def pode_ver_solicitacao_verba(user, solicitacao):
    return solicitacao.usuario_solicitante_id == user.id or no_grupo(user, *GESTAO_FINANCEIRA, *CONTAS_A_PAGAR)


def grupo_requerido(*grupos, destino='home', json=False):
    """
    Exige login e pelo menos um dos grupos. Sem permissão:
    - telas: volta para `destino` com uma mensagem;
    - chamadas JSON: responde 403.
    """
    def decorator(view):
        @login_required
        @wraps(view)
        def _view(request, *args, **kwargs):
            if no_grupo(request.user, *grupos):
                return view(request, *args, **kwargs)
            if json:
                return JsonResponse({'erro': 'Sem permissão.'}, status=403)
            messages.error(request, "Você não tem permissão para esta ação.")
            return redirect(destino)
        return _view
    return decorator
