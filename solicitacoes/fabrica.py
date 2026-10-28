"""
Tela da Fábrica: só os pedidos de chopp de HOJE que já foram enviados (dia confirmado).

A fábrica confere o que o cliente levou: ajusta quantidades, tira ou inclui produtos e marca
ENTREGUE, ou marca "não retirou" (o pedido fica CANCELADO). Sem preços na tela; produto incluído
pela fábrica pega o preço da tabela do cliente (ou fica zerado para o Faturamento informar).
Depois disso o pedido segue para o Faturamento, que processa Enviado ou Entregue.
"""
import logging

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from app.permissoes import eh_somente_fabrica, grupo_requerido
from app.protheus import ProtheusIndisponivel

from . import agendamento, protheus_chopp
from .models import SolicitacaoChopp, SolicitacaoChoppItem

logger = logging.getLogger(__name__)

FABRICA = ('Fábrica',)
MSG_PROTHEUS = agendamento.MSG_PROTHEUS


def _pedidos_do_dia():
    return (SolicitacaoChopp.objects.filter(data_retirada=agendamento.hoje(), status__in=['ENVIADO', 'ENTREGUE', 'CANCELADO'])
            .exclude(status='CANCELADO', entregue_por__isnull=True)      # cancelado fora da fábrica não aparece
            .select_related('vendedor', 'entregue_por').prefetch_related('itens')
            .order_by('hora_retirada', 'cliente_razao_social'))


@never_cache   # inadimplência sempre do Protheus, sem o navegador reaproveitar a página
@grupo_requerido(*FABRICA)
def fabrica_dia(request):
    pedidos = list(_pedidos_do_dia())
    abertos = [p for p in pedidos if p.status == 'ENVIADO']
    inad = agendamento.inadimplencia_dos_clientes({(p.cliente_codigo, p.cliente_loja) for p in abertos})
    for p in pedidos:
        p.inadimplencia = (inad or {}).get((p.cliente_codigo.strip(), p.cliente_loja.strip())) if p.status == 'ENVIADO' else None
        p.itens_ativos = [i for i in p.itens.all() if not i.removido]
    return render(request, 'solicitacoes/fabrica.html', {
        'pedidos': pedidos,
        'hoje': agendamento.hoje(),
        'qtd_abertos': len(abertos),
        'litros_abertos': sum(p.litros for p in abertos),
        'litros_entregues': sum(p.litros for p in pedidos if p.status == 'ENTREGUE'),
        'inadimplencia_indisponivel': inad is None,
        'tela_unica': eh_somente_fabrica(request.user),     # sem menu: só esta tela e o botão Sair
    })


def _ler_quantidades(post, pedido, erros):
    """
    Lê o formulário de um pedido: quantidades dos itens existentes (0 = não levou) e produtos incluídos.
    Retorna (alteracoes {item: qtd}, novos [(codigo, qtd)]).
    """
    alteracoes = {}
    for item in pedido.itens.all():
        if item.removido:
            continue
        valor = post.get(f'qtd_{item.id}')
        try:
            qtd = int(valor)
        except (TypeError, ValueError):
            erros.append(f"Quantidade inválida para '{item.produto_descricao}'.")
            continue
        if qtd < 0:
            erros.append(f"Quantidade inválida para '{item.produto_descricao}'.")
            continue
        alteracoes[item] = qtd
    novos = []
    for chave in post:
        if chave.startswith('novo_codigo_'):
            n = chave.rsplit('_', 1)[-1]
            codigo = (post.get(chave) or '').strip()
            try:
                qtd = int(post.get(f'novo_qtd_{n}') or 0)
            except ValueError:
                qtd = 0
            if codigo and qtd > 0:
                novos.append((codigo, qtd))
    if not any(q > 0 for q in alteracoes.values()) and not novos:
        erros.append("Nenhum produto com quantidade. Se o cliente não levou nada, use \"Não retirou\".")
    return alteracoes, novos


@grupo_requerido(*FABRICA, destino='fabrica_dia')
def fabrica_entregar(request, pk):
    """Grava o que saiu de fato e marca o pedido como ENTREGUE."""
    if request.method != 'POST':
        return redirect('fabrica_dia')
    pedido = get_object_or_404(SolicitacaoChopp.objects.prefetch_related('itens'), pk=pk)
    if pedido.status != 'ENVIADO' or pedido.data_retirada != agendamento.hoje():
        messages.error(request, f"O pedido #{pedido.id} não está mais aguardando retirada.")
        return redirect('fabrica_dia')

    erros = []
    alteracoes, novos = _ler_quantidades(request.POST, pedido, erros)
    validos, precos = {}, {}
    if novos and not erros:
        try:
            validos = protheus_chopp.produtos_validos([c for c, _ in novos])
            precos = protheus_chopp.precos_tabela(pedido.tabela_preco, list(validos))
        except ProtheusIndisponivel as e:
            logger.error("Retirada não gravada: %s", e)
            erros.append(MSG_PROTHEUS)
        for codigo, _ in novos:
            if validos and codigo not in validos:
                erros.append(f"O produto {codigo} não é um produto de chopp ativo no Protheus.")
    if erros:
        for e in erros:
            messages.error(request, f"Pedido #{pedido.id}: {e}")
        return redirect('fabrica_dia')

    with transaction.atomic():
        pedido = SolicitacaoChopp.objects.select_for_update().get(pk=pedido.pk)
        if pedido.status != 'ENVIADO':
            messages.error(request, f"O pedido #{pedido.id} foi alterado por outra pessoa.")
            return redirect('fabrica_dia')
        for item, qtd in alteracoes.items():
            if qtd == 0:
                if item.qtd_solicitada is None:        # incluído depois e tirado: apaga
                    item.delete()
                    continue
                item.removido, item.quantidade = True, 0
            else:
                item.quantidade = qtd
            item.save()
        existentes = {i.produto_codigo: i for i in pedido.itens.all() if not i.removido}
        for codigo, qtd in novos:
            if codigo in existentes:                   # produto que já estava: soma
                existentes[codigo].quantidade += qtd
                existentes[codigo].save()
                continue
            preco = precos.get(codigo)
            SolicitacaoChoppItem.objects.create(
                solicitacao=pedido, produto_codigo=codigo, produto_descricao=validos[codigo]['descricao'][:100],
                quantidade=qtd, preco_unitario=preco if preco is not None else 0, preco_da_tabela=preco is not None,
                incluido_por='FABRICA')
        pedido.status = 'ENTREGUE'
        pedido.entregue_por, pedido.entregue_em = request.user, timezone.now()
        pedido.save()
    messages.success(request, f"Pedido #{pedido.id} ({pedido.cliente_nome}) marcado como entregue.")
    return redirect('fabrica_dia')


@grupo_requerido(*FABRICA, destino='fabrica_dia')
def fabrica_nao_retirou(request, pk):
    if request.method != 'POST':
        return redirect('fabrica_dia')
    with transaction.atomic():
        pedido = get_object_or_404(SolicitacaoChopp.objects.select_for_update(), pk=pk)
        if pedido.status != 'ENVIADO' or pedido.data_retirada != agendamento.hoje():
            messages.error(request, f"O pedido #{pedido.id} não está mais aguardando retirada.")
            return redirect('fabrica_dia')
        obs = (request.POST.get('motivo') or '').strip()
        pedido.status = 'CANCELADO'
        pedido.motivo_cancelamento = "Cliente não retirou" + (f": {obs}" if obs else ".")
        pedido.cancelado_por = request.user
        pedido.data_cancelamento = timezone.now()
        pedido.entregue_por, pedido.entregue_em = request.user, timezone.now()   # registro de quem conferiu na fábrica
        pedido.save()
    messages.success(request, f"Pedido #{pedido.id} ({pedido.cliente_nome}) marcado como não retirado.")
    return redirect('fabrica_dia')


@grupo_requerido(*FABRICA, json=True)
def fabrica_api_produtos(request):
    """Busca de produtos de chopp para a fábrica incluir (sem preço)."""
    try:
        return JsonResponse(protheus_chopp.buscar_produtos(request.GET.get('q')), safe=False)
    except ProtheusIndisponivel:
        return JsonResponse({'erro': MSG_PROTHEUS}, status=503)
