"""
Solicitação de Chopp.

Fluxo: o pedido nasce no Agendamento (PENDENTE -> AGENDADO) e chega aqui como ENVIADO quando a
Gestão Comercial confirma o dia; vira ENTREGUE quando a fábrica marca a retirada. O Faturamento confere o que saiu, corrige produtos/quantidades
se precisar, informa o número do pedido do Protheus e FINALIZA, ou CANCELA.
A condição de pagamento vem do cadastro do cliente e ninguém altera.

Acesso (vendedor não entra nesta tela):
- Faturamento: vê todos, processa e cancela;
- Gestão Comercial e Gestão Financeira: acompanham todos e exportam para Excel.
"""
import logging
from decimal import Decimal, InvalidOperation

import pandas as pd
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from app.permissoes import grupo_requerido, no_grupo
from app.protheus import ProtheusIndisponivel

from . import agendamento, protheus_chopp

from .models import SolicitacaoChopp, SolicitacaoChoppItem

logger = logging.getLogger(__name__)

GESTAO_CHOPP = ('Gestão Comercial', 'Gestão Financeira')   # acompanham e exportam
FATURAMENTO_CHOPP = ('Faturamento',)                        # corrige, finaliza e cancela
CHOPP_ACESSO = GESTAO_CHOPP + FATURAMENTO_CHOPP             # quem entra na tela


# ------------------------------------------------------------------ regras
def eh_gestor_chopp(user):
    return no_grupo(user, *GESTAO_CHOPP)


def eh_faturamento(user):
    return no_grupo(user, *FATURAMENTO_CHOPP)


# O Faturamento processa e cancela o que já foi enviado (antes ou depois de a fábrica marcar a entrega)
PROCESSAVEIS = ('ENVIADO', 'ENTREGUE')


def pedidos_visiveis(user):
    """A tela do Chopp começa no ENVIADO; pendentes e agendados ficam só no calendário."""
    return SolicitacaoChopp.objects.exclude(status__in=['PENDENTE', 'AGENDADO']).select_related('vendedor').prefetch_related('itens')


# ------------------------------------------------------------------ leitura do formulário
def _decimal(valor):
    texto = str(valor or '').strip().replace('R$', '').replace(' ', '')
    if ',' in texto:
        texto = texto.replace('.', '').replace(',', '.')
    try:
        return Decimal(texto).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def _ler_itens(p, erros, permite_remover=False):
    """Itens do formulário. Com permite_remover, item marcado como removido não precisa de quantidade/preço."""
    itens = []
    indices = sorted({k.rsplit('_', 1)[-1] for k in p if k.startswith('item_codigo_')}, key=lambda i: int(i) if i.isdigit() else 0)
    for i in indices:
        codigo = (p.get(f'item_codigo_{i}') or '').strip()
        nome = (p.get(f'item_nome_{i}') or '').strip()
        if not codigo:
            continue
        item_id = p.get(f'item_id_{i}')
        removido = permite_remover and p.get(f'item_removido_{i}') == '1'
        try:
            qtd = int(p.get(f'item_qtd_{i}') or 0)
        except ValueError:
            qtd = 0
        preco = _decimal(p.get(f'item_preco_{i}'))
        if not removido:
            if qtd <= 0:
                erros.append(f"Quantidade inválida para '{nome}'.")
            if preco is None or preco <= 0:
                erros.append(f"Informe o preço de '{nome}'.")
        itens.append({
            'id': int(item_id) if item_id and item_id.isdigit() else None,
            'codigo': codigo, 'nome': nome, 'qtd': qtd, 'preco': preco, 'removido': removido,
        })
    if not any(not it['removido'] for it in itens):
        erros.append("O pedido precisa ter pelo menos um produto.")
    return itens


def _estado_inicial(pedido, post=None):
    """Valores para preencher a tela do Faturamento: do POST com erro, ou do pedido salvo."""
    estado = {
        'observacao': pedido.observacao,
        'tabela_preco': pedido.tabela_preco,
        'pedido_protheus': post.get('pedido_protheus', '') if post is not None else pedido.pedido_protheus,
        'observacao_faturamento': post.get('observacao_faturamento', '') if post is not None else pedido.observacao_faturamento,
    }
    originais = {i.id: i for i in pedido.itens.all()}
    if post is not None:
        estado['itens'] = []
        indices = sorted({k.rsplit('_', 1)[-1] for k in post if k.startswith('item_codigo_')}, key=lambda i: int(i) if i.isdigit() else 0)
        for i in indices:
            item_id = post.get(f'item_id_{i}')
            orig = originais.get(int(item_id)) if item_id and item_id.isdigit() else None
            estado['itens'].append({
                'id': orig.id if orig else None, 'codigo': post.get(f'item_codigo_{i}', ''), 'nome': post.get(f'item_nome_{i}', ''),
                'qtd': post.get(f'item_qtd_{i}', ''), 'preco': post.get(f'item_preco_{i}', ''),
                'removido': post.get(f'item_removido_{i}') == '1',
                'qtd_solicitada': orig.qtd_solicitada if orig else None,
                'preco_solicitado': str(orig.preco_solicitado) if orig and orig.preco_solicitado is not None else None,
                'incluido_por': orig.incluido_por if orig else '',
            })
        return estado
    estado['itens'] = [{
        'id': i.id, 'codigo': i.produto_codigo, 'nome': i.produto_descricao,
        'qtd': i.qtd_solicitada if i.removido else i.quantidade, 'preco': str(i.preco_unitario),
        'removido': i.removido,
        'qtd_solicitada': i.qtd_solicitada,
        'preco_solicitado': str(i.preco_solicitado) if i.preco_solicitado is not None else None,
        'incluido_por': i.incluido_por,
    } for i in originais.values()]
    return estado


def _marcar_inadimplencia(pedidos):
    """Alerta de inadimplência (o mesmo do Agendamento) nos pedidos que o Faturamento ainda vai processar."""
    inad = agendamento.inadimplencia_dos_clientes({(p.cliente_codigo, p.cliente_loja) for p in pedidos})
    for p in pedidos:
        p.inadimplencia = (inad or {}).get((p.cliente_codigo.strip(), p.cliente_loja.strip()))
    return inad


def _contexto_form(pedido, dados_post=None):
    _marcar_inadimplencia([pedido])
    return {
        'titulo': f'Processar Pedido de Chopp #{pedido.id}',
        'pedido': pedido,
        'estado': _estado_inicial(pedido, dados_post),
    }


# ------------------------------------------------------------------ telas
@never_cache   # inadimplência sempre do Protheus, sem o navegador reaproveitar a página
@grupo_requerido(*CHOPP_ACESSO)
def chopp_list(request):
    pedidos = pedidos_visiveis(request.user)

    status = request.GET.get('status')
    busca = (request.GET.get('busca') or '').strip()
    vendedor_id = request.GET.get('vendedor')
    data_ini = request.GET.get('data_ini')
    data_fim = request.GET.get('data_fim')
    if status:
        pedidos = pedidos.filter(status=status)
    if busca:
        filtro = Q(cliente_razao_social__icontains=busca) | Q(cliente_nome_fantasia__icontains=busca) | \
            Q(cliente_cpf_cnpj__icontains=busca) | Q(pedido_protheus__icontains=busca)
        if busca.isdigit() and len(busca) < 9:
            filtro |= Q(id=int(busca))
        pedidos = pedidos.filter(filtro)
    if vendedor_id:
        pedidos = pedidos.filter(vendedor_id=vendedor_id)
    if data_ini:
        pedidos = pedidos.filter(data_retirada__gte=data_ini)
    if data_fim:
        pedidos = pedidos.filter(data_retirada__lte=data_fim)

    pagina = Paginator(pedidos.order_by('-data_retirada', '-hora_retirada', '-id'), 10).get_page(request.GET.get('page'))
    inad = _marcar_inadimplencia([p for p in pagina if p.status in PROCESSAVEIS])
    return render(request, 'solicitacoes/chopp_list.html', {
        'pedidos': pagina,
        'inadimplencia_indisponivel': inad is None,
        'processaveis': PROCESSAVEIS,
        'pode_exportar': eh_gestor_chopp(request.user),
        'eh_faturamento': eh_faturamento(request.user),
        'vendedores': User.objects.filter(groups__name='Vendedores', is_active=True).distinct().order_by('first_name'),
        'status_choices': [c for c in SolicitacaoChopp.STATUS_CHOICES if c[0] not in ('PENDENTE', 'AGENDADO')],
    })


@never_cache   # inadimplência sempre do Protheus, sem o navegador reaproveitar a página
@grupo_requerido(*FATURAMENTO_CHOPP, destino='chopp_list')
def chopp_processar(request, pk):
    """Faturamento confere, corrige o que o cliente realmente levou e finaliza com o número do pedido."""
    pedido = get_object_or_404(SolicitacaoChopp.objects.prefetch_related('itens'), pk=pk)
    if pedido.status not in PROCESSAVEIS:
        messages.error(request, f"O pedido #{pedido.id} está {pedido.get_status_display().lower()} e não pode ser processado.")
        return redirect('chopp_list')

    if request.method == 'POST':
        p = request.POST
        erros = []
        # O Faturamento só altera a grade de produtos; cliente, retirada, condição e observação do vendedor ficam como estão
        itens = _ler_itens(p, erros, permite_remover=True)
        observacao_fat = (p.get('observacao_faturamento') or '').strip()
        finalizar = p.get('acao') == 'finalizar'
        numero_pedido = (p.get('pedido_protheus') or '').strip()
        if finalizar and not numero_pedido:
            erros.append("Informe o número do pedido gerado no Protheus para finalizar.")
        if len(numero_pedido) > 6:
            erros.append("O número do pedido do Protheus tem no máximo 6 caracteres.")

        with transaction.atomic():
            pedido = SolicitacaoChopp.objects.select_for_update().get(pk=pedido.pk)
            if pedido.status not in PROCESSAVEIS:
                messages.error(request, "Este pedido já foi processado por outra pessoa.")
                return redirect('chopp_list')

            if not erros:
                existentes = {i.id: i for i in pedido.itens.all()}
                antes = {i.id: (i.quantidade, i.preco_unitario, i.removido) for i in existentes.values()}
                mexeu = False      # o Faturamento alterou algo agora (ajustes da fábrica não contam)
                vistos = set()
                for it in itens:
                    atual = existentes.get(it['id'])
                    if atual:
                        vistos.add(atual.id)
                        if it['removido']:
                            if atual.qtd_solicitada is None:      # incluído depois do pedido e tirado: apaga
                                atual.delete()
                                mexeu = True
                                continue
                            atual.removido, atual.quantidade = True, 0
                        else:
                            atual.removido, atual.quantidade, atual.preco_unitario = False, it['qtd'], it['preco']
                        mexeu = mexeu or (atual.quantidade, atual.preco_unitario, atual.removido) != antes[atual.id]
                        atual.save()
                    elif not it['removido']:
                        SolicitacaoChoppItem.objects.create(
                            solicitacao=pedido, produto_codigo=it['codigo'], produto_descricao=it['nome'],
                            quantidade=it['qtd'], preco_unitario=it['preco'], incluido_por='FATURAMENTO')
                        mexeu = True
                for item_id, atual in existentes.items():
                    if item_id not in vistos:                    # não veio no formulário: trata como removido
                        mexeu = True
                        if atual.qtd_solicitada is None:
                            atual.delete()
                        else:
                            atual.removido, atual.quantidade = True, 0
                            atual.save()

                pedido.observacao_faturamento = observacao_fat
                pedido.alterado_pelo_faturamento = pedido.alterado_pelo_faturamento or mexeu
                if pedido.alterado_pelo_faturamento and not observacao_fat:
                    erros.append("Explique na observação do Faturamento o que foi alterado e por quê.")

            if erros:
                transaction.set_rollback(True)
            else:
                pedido.pedido_protheus = numero_pedido
                pedido.usuario_faturamento = request.user
                if finalizar:
                    pedido.status = 'FINALIZADO'
                    pedido.data_finalizacao = timezone.now()
                pedido.save()

        if erros:
            pedido = SolicitacaoChopp.objects.prefetch_related('itens').get(pk=pedido.pk)
            for e in erros:
                messages.error(request, e)
            return render(request, 'solicitacoes/chopp_form.html', _contexto_form(pedido, request.POST))

        if finalizar:
            messages.success(request, f"Pedido de chopp #{pedido.id} finalizado (Protheus {numero_pedido}).")
        else:
            messages.success(request, f"Alterações do pedido #{pedido.id} salvas. Ele continua aguardando finalização.")
        return redirect('chopp_list')

    return render(request, 'solicitacoes/chopp_form.html', _contexto_form(pedido))


@grupo_requerido(*FATURAMENTO_CHOPP, destino='chopp_list')
def chopp_cancelar(request, pk):
    if request.method != 'POST':
        return redirect('chopp_list')
    pedido = get_object_or_404(SolicitacaoChopp, pk=pk)
    if pedido.status not in PROCESSAVEIS:
        messages.error(request, f"O pedido #{pedido.id} já está {pedido.get_status_display().lower()}.")
        return redirect('chopp_list')
    motivo = (request.POST.get('motivo') or '').strip()
    if not motivo:
        messages.error(request, "Informe o motivo do cancelamento.")
        return redirect('chopp_list')
    pedido.status = 'CANCELADO'
    pedido.motivo_cancelamento = motivo
    pedido.cancelado_por = request.user
    pedido.data_cancelamento = timezone.now()
    pedido.save()
    messages.success(request, f"Pedido de chopp #{pedido.id} cancelado.")
    return redirect('chopp_list')


@grupo_requerido(*GESTAO_CHOPP, destino='chopp_list')
def chopp_exportar(request):
    pedidos = pedidos_visiveis(request.user).select_related('usuario_faturamento')
    if request.GET.get('data_ini'):
        pedidos = pedidos.filter(data_retirada__gte=request.GET['data_ini'])
    if request.GET.get('data_fim'):
        pedidos = pedidos.filter(data_retirada__lte=request.GET['data_fim'])
    if request.GET.get('status'):
        pedidos = pedidos.filter(status=request.GET['status'])
    if request.GET.get('vendedor'):
        pedidos = pedidos.filter(vendedor_id=request.GET['vendedor'])

    linhas_excel = []
    for p in pedidos.order_by('data_retirada', 'hora_retirada', 'id'):
        for it in p.itens.all():
            linhas_excel.append({
                'Pedido': p.id,
                'Data da retirada': p.data_retirada,
                'Horário': p.horario,
                'Agendado em': timezone.localtime(p.data_solicitacao).replace(tzinfo=None),
                'Vendedor': p.vendedor.get_full_name() or p.vendedor.username,
                'Cliente': p.cliente_razao_social,
                'CPF/CNPJ': p.cliente_cpf_cnpj,
                'Código/Loja': f"{p.cliente_codigo}/{p.cliente_loja}",
                'Condição de pagamento': f"{p.condicao_pagamento} - {p.condicao_pagamento_descricao}",
                'Produto': f"{it.produto_codigo} - {it.produto_descricao}",
                'Qtd solicitada': it.qtd_solicitada if it.qtd_solicitada is not None else '',
                'Qtd final': it.quantidade,
                'Preço solicitado': it.preco_solicitado if it.preco_solicitado is not None else '',
                'Preço final': it.preco_unitario,
                'Total do item': it.valor_total,
                'Situação do item': it.situacao_display,
                'Status': p.get_status_display(),
                'Pedido Protheus': p.pedido_protheus,
                'Faturamento': (p.usuario_faturamento.get_full_name() or p.usuario_faturamento.username) if p.usuario_faturamento else '',
                'Observação do vendedor': p.observacao,
                'Observação do Faturamento': p.observacao_faturamento,
                'Motivo cancelamento': p.motivo_cancelamento,
            })

    resposta = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resposta['Content-Disposition'] = f"attachment; filename=pedidos_chopp_{timezone.localdate():%Y%m%d}.xlsx"
    with pd.ExcelWriter(resposta, engine='openpyxl') as writer:
        pd.DataFrame(linhas_excel).to_excel(writer, index=False, sheet_name='Chopp')
    return resposta


@grupo_requerido(*FATURAMENTO_CHOPP, json=True)
def api_busca_produtos_chopp(request):
    """Produtos de chopp; com ?tabela= traz também o preço da tabela do cliente (ou vazio)."""
    try:
        produtos = protheus_chopp.buscar_produtos(request.GET.get('q'))
        precos = protheus_chopp.precos_tabela(request.GET.get('tabela'), [p['codigo'] for p in produtos])
    except ProtheusIndisponivel:
        return JsonResponse({'erro': 'Não foi possível consultar o Protheus agora. Tente novamente em instantes.'}, status=503)
    for p in produtos:
        preco = precos.get(p['codigo'])
        p['preco'] = str(preco) if preco is not None else None
    return JsonResponse(produtos, safe=False)
