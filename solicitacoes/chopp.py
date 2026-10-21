"""
Solicitação de Chopp.

Fluxo: o vendedor lança o pedido (fica PENDENTE) -> o Faturamento confere, corrige se precisar,
informa o número do pedido do Protheus e FINALIZA, ou CANCELA. Não há aprovação.

Visibilidade:
- vendedor: só os próprios pedidos, e só os lançados no dia útil anterior e hoje;
- Gestão Comercial e Faturamento: todos, com filtros e exportação para Excel.
"""
import logging
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

import pandas as pd
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.contrib.auth.models import User
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from app.permissoes import grupo_requerido, no_grupo
from app.protheus import ProtheusIndisponivel, consultar, linhas

from .models import SolicitacaoChopp, SolicitacaoChoppItem

logger = logging.getLogger(__name__)

GESTAO_CHOPP = ('Gestão Comercial', 'Faturamento')     # veem tudo, filtram e exportam
FATURAMENTO_CHOPP = ('Faturamento',)                    # corrige, finaliza e cancela
CHOPP_ACESSO = ('Vendedores',) + GESTAO_CHOPP           # quem entra na tela

# Grupos de produto do Protheus que podem ser pedidos como chopp
GRUPOS_PRODUTO_CHOPP = ['0019', '0020', '0027', '0028', '0033']
FILIAL_PRODUTO_CHOPP = '0101'


# ------------------------------------------------------------------ regras
def eh_gestor_chopp(user):
    return no_grupo(user, *GESTAO_CHOPP)


def eh_faturamento(user):
    return no_grupo(user, *FATURAMENTO_CHOPP)


def inicio_janela_vendedor(agora=None):
    """Meia-noite do dia útil anterior (segunda-feira volta para sexta)."""
    agora = timezone.localtime(agora or timezone.now())
    dia = agora.date() - timedelta(days=1)
    while dia.weekday() >= 5:          # sábado=5, domingo=6
        dia -= timedelta(days=1)
    return timezone.make_aware(datetime.combine(dia, time.min), timezone.get_current_timezone())


def pedidos_visiveis(user):
    qs = SolicitacaoChopp.objects.select_related('vendedor').prefetch_related('itens')
    if eh_gestor_chopp(user):
        return qs
    return qs.filter(vendedor=user, data_solicitacao__gte=inicio_janela_vendedor())


def _pedido_visivel_ou_404(user, pk):
    pedido = pedidos_visiveis(user).filter(pk=pk).first()
    if not pedido:
        raise Http404("Pedido não encontrado.")
    return pedido


def pode_editar_como_vendedor(user, pedido):
    """Dono do pedido, ainda pendente e sem o Faturamento ter começado a conferir."""
    return pedido.status == 'PENDENTE' and pedido.vendedor_id == user.id and pedido.usuario_faturamento_id is None


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


def _ler_formulario(request, exige_data_futura=True):
    """Formulário do vendedor (novo ou editar). Retorna (dados, itens, erros)."""
    p = request.POST
    erros = []
    dados = {
        'cliente_codigo': (p.get('cliente_codigo') or '').strip(),
        'cliente_loja': (p.get('cliente_loja') or '').strip(),
        'cliente_razao_social': (p.get('cliente_razao_social') or '').strip(),
        'cliente_nome_fantasia': (p.get('cliente_nome_fantasia') or '').strip(),
        'cliente_cpf_cnpj': (p.get('cliente_cpf_cnpj') or '').strip(),
        'recebimento': p.get('recebimento') or '',
        'data_entrega': None,
        'prazo_pagamento': (p.get('prazo_pagamento') or '').strip(),
        'observacao': (p.get('observacao') or '').strip(),
    }
    if not (dados['cliente_codigo'] and dados['cliente_razao_social'] and dados['cliente_cpf_cnpj']):
        erros.append("Selecione o cliente pela busca do Protheus.")
    if dados['recebimento'] not in dict(SolicitacaoChopp.RECEBIMENTO_CHOICES):
        erros.append("Informe se é retirada na Fábrica, retirada na Logística ou entrega.")
    if dados['recebimento'] == 'ENTREGA':
        try:
            dados['data_entrega'] = datetime.strptime(p.get('data_entrega') or '', '%Y-%m-%d').date()
        except ValueError:
            erros.append("Informe a data de entrega.")
        else:
            if exige_data_futura and dados['data_entrega'] < timezone.localdate():
                erros.append("A data de entrega não pode ser anterior a hoje.")
    if dados['prazo_pagamento'] not in dict(SolicitacaoChopp.PRAZO_CHOICES):
        erros.append("Selecione o prazo de pagamento.")
    dados['prazo_pagamento_solicitado'] = dados['prazo_pagamento']
    itens = _ler_itens(p, erros)
    return dados, itens, erros


def _estado_inicial(pedido=None, post=None):
    """Valores para preencher o formulário: do POST com erro, ou do pedido salvo."""
    campos = ['cliente_codigo', 'cliente_loja', 'cliente_razao_social', 'cliente_nome_fantasia', 'cliente_cpf_cnpj',
              'recebimento', 'data_entrega', 'prazo_pagamento', 'observacao', 'pedido_protheus',
              'observacao_faturamento', 'prazo_pagamento_solicitado']
    if post is not None:
        estado = {c: post.get(c, '') for c in campos}
        if pedido:  # o que só o vendedor define continua vindo do pedido salvo
            for c in ['cliente_codigo', 'cliente_loja', 'cliente_razao_social', 'cliente_nome_fantasia', 'cliente_cpf_cnpj',
                      'recebimento', 'observacao', 'prazo_pagamento_solicitado']:
                estado.setdefault(c, '')
                if not post.get(c):
                    estado[c] = getattr(pedido, c) or ''
            if not post.get('data_entrega') and pedido.data_entrega:
                estado['data_entrega'] = pedido.data_entrega.isoformat()
        originais = {i.id: i for i in pedido.itens.all()} if pedido else {}
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
            })
        return estado
    if pedido is None:
        return {'itens': []}
    estado = {c: getattr(pedido, c) or '' for c in campos}
    estado['data_entrega'] = pedido.data_entrega.isoformat() if pedido.data_entrega else ''
    estado['itens'] = [{
        'id': i.id, 'codigo': i.produto_codigo, 'nome': i.produto_descricao,
        'qtd': i.qtd_solicitada if i.removido else i.quantidade, 'preco': str(i.preco_unitario),
        'removido': i.removido,
        'qtd_solicitada': i.qtd_solicitada,
        'preco_solicitado': str(i.preco_solicitado) if i.preco_solicitado is not None else None,
    } for i in pedido.itens.all()]
    return estado


def _contexto_form(titulo, modo, pedido=None, dados_post=None):
    return {
        'titulo': titulo,
        'modo': modo,                       # 'novo', 'editar' ou 'processar'
        'pedido': pedido,
        'estado': _estado_inicial(pedido, dados_post),
        'recebimento_choices': SolicitacaoChopp.RECEBIMENTO_CHOICES,
        'prazo_choices': SolicitacaoChopp.PRAZO_CHOICES,
    }


# ------------------------------------------------------------------ telas
@grupo_requerido(*CHOPP_ACESSO)
def chopp_list(request):
    gestor = eh_gestor_chopp(request.user)
    pedidos = pedidos_visiveis(request.user)

    status = request.GET.get('status')
    if status:
        pedidos = pedidos.filter(status=status)

    if gestor:
        busca = (request.GET.get('busca') or '').strip()
        vendedor_id = request.GET.get('vendedor')
        data_ini = request.GET.get('data_ini')
        data_fim = request.GET.get('data_fim')
        if busca:
            filtro = Q(cliente_razao_social__icontains=busca) | Q(cliente_nome_fantasia__icontains=busca) | \
                Q(cliente_cpf_cnpj__icontains=busca) | Q(pedido_protheus__icontains=busca)
            if busca.isdigit() and len(busca) < 9:
                filtro |= Q(id=int(busca))
            pedidos = pedidos.filter(filtro)
        if vendedor_id:
            pedidos = pedidos.filter(vendedor_id=vendedor_id)
        if data_ini:
            pedidos = pedidos.filter(data_solicitacao__date__gte=data_ini)
        if data_fim:
            pedidos = pedidos.filter(data_solicitacao__date__lte=data_fim)

    pagina = Paginator(pedidos.order_by('-data_solicitacao'), 10).get_page(request.GET.get('page'))
    return render(request, 'solicitacoes/chopp_list.html', {
        'pedidos': pagina,
        'eh_gestor': gestor,
        'eh_faturamento': eh_faturamento(request.user),
        'vendedores': User.objects.filter(groups__name='Vendedores', is_active=True).distinct().order_by('first_name') if gestor else [],
        'inicio_janela': inicio_janela_vendedor(),
        'status_choices': SolicitacaoChopp.STATUS_CHOICES,
    })


@grupo_requerido(*CHOPP_ACESSO)
def chopp_novo(request):
    if request.method == 'POST':
        dados, itens, erros = _ler_formulario(request)
        if erros:
            for e in erros:
                messages.error(request, e)
            return render(request, 'solicitacoes/chopp_form.html', _contexto_form('Nova Solicitação de Chopp', 'novo', dados_post=request.POST))
        with transaction.atomic():
            pedido = SolicitacaoChopp.objects.create(vendedor=request.user, **dados)
            for it in itens:
                SolicitacaoChoppItem.objects.create(
                    solicitacao=pedido, produto_codigo=it['codigo'], produto_descricao=it['nome'],
                    quantidade=it['qtd'], preco_unitario=it['preco'],
                    qtd_solicitada=it['qtd'], preco_solicitado=it['preco'])
        messages.success(request, f"Pedido de chopp #{pedido.id} enviado para o Faturamento.")
        return redirect('chopp_list')
    return render(request, 'solicitacoes/chopp_form.html', _contexto_form('Nova Solicitação de Chopp', 'novo'))


@grupo_requerido(*CHOPP_ACESSO)
def chopp_editar(request, pk):
    pedido = _pedido_visivel_ou_404(request.user, pk)
    if not pode_editar_como_vendedor(request.user, pedido):
        messages.error(request, "Este pedido não pode mais ser editado.")
        return redirect('chopp_list')

    if request.method == 'POST':
        dados, itens, erros = _ler_formulario(request)
        if erros:
            for e in erros:
                messages.error(request, e)
            return render(request, 'solicitacoes/chopp_form.html', _contexto_form(f'Editar Pedido de Chopp #{pedido.id}', 'editar', pedido, request.POST))
        with transaction.atomic():
            pedido = SolicitacaoChopp.objects.select_for_update().get(pk=pedido.pk)
            if pedido.status != 'PENDENTE':
                messages.error(request, "O Faturamento já processou este pedido; a edição não foi salva.")
                return redirect('chopp_list')
            for campo, valor in dados.items():
                setattr(pedido, campo, valor)
            pedido.save()
            pedido.itens.all().delete()
            for it in itens:
                SolicitacaoChoppItem.objects.create(
                    solicitacao=pedido, produto_codigo=it['codigo'], produto_descricao=it['nome'],
                    quantidade=it['qtd'], preco_unitario=it['preco'],
                    qtd_solicitada=it['qtd'], preco_solicitado=it['preco'])
        messages.success(request, f"Pedido de chopp #{pedido.id} atualizado.")
        return redirect('chopp_list')
    return render(request, 'solicitacoes/chopp_form.html', _contexto_form(f'Editar Pedido de Chopp #{pedido.id}', 'editar', pedido))


@grupo_requerido(*FATURAMENTO_CHOPP, destino='chopp_list')
def chopp_processar(request, pk):
    """Faturamento confere, corrige o que o cliente realmente levou e finaliza com o número do pedido."""
    pedido = get_object_or_404(SolicitacaoChopp.objects.prefetch_related('itens'), pk=pk)
    if pedido.status != 'PENDENTE':
        messages.error(request, f"O pedido #{pedido.id} já está {pedido.get_status_display().lower()}.")
        return redirect('chopp_list')

    if request.method == 'POST':
        p = request.POST
        erros = []
        # O Faturamento só altera o prazo e a grade de produtos; cliente, recebimento e observação do vendedor ficam como estão
        prazo = (p.get('prazo_pagamento') or '').strip()
        if prazo not in dict(SolicitacaoChopp.PRAZO_CHOICES):
            erros.append("Selecione o prazo de pagamento.")
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
            if pedido.status != 'PENDENTE':
                messages.error(request, "Este pedido já foi processado por outra pessoa.")
                return redirect('chopp_list')

            if not erros:
                existentes = {i.id: i for i in pedido.itens.all()}
                vistos = set()
                for it in itens:
                    atual = existentes.get(it['id'])
                    if atual:
                        vistos.add(atual.id)
                        if it['removido']:
                            if atual.qtd_solicitada is None:      # incluído pelo Faturamento e depois tirado: apaga
                                atual.delete()
                                continue
                            atual.removido, atual.quantidade = True, 0
                        else:
                            atual.removido, atual.quantidade, atual.preco_unitario = False, it['qtd'], it['preco']
                        atual.save()
                    elif not it['removido']:
                        SolicitacaoChoppItem.objects.create(
                            solicitacao=pedido, produto_codigo=it['codigo'], produto_descricao=it['nome'],
                            quantidade=it['qtd'], preco_unitario=it['preco'])
                for item_id, atual in existentes.items():
                    if item_id not in vistos:                    # não veio no formulário: trata como removido
                        if atual.qtd_solicitada is None:
                            atual.delete()
                        else:
                            atual.removido, atual.quantidade = True, 0
                            atual.save()

                pedido.prazo_pagamento = prazo
                pedido.observacao_faturamento = observacao_fat
                pedido.alterado_pelo_faturamento = pedido.tem_alteracao_do_faturamento()
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
            return render(request, 'solicitacoes/chopp_form.html', _contexto_form(f'Processar Pedido de Chopp #{pedido.id}', 'processar', pedido, request.POST))

        if finalizar:
            messages.success(request, f"Pedido de chopp #{pedido.id} finalizado (Protheus {numero_pedido}).")
        else:
            messages.success(request, f"Alterações do pedido #{pedido.id} salvas. Ele continua pendente.")
        return redirect('chopp_list')

    return render(request, 'solicitacoes/chopp_form.html', _contexto_form(f'Processar Pedido de Chopp #{pedido.id}', 'processar', pedido))


@grupo_requerido(*CHOPP_ACESSO)
def chopp_cancelar(request, pk):
    if request.method != 'POST':
        return redirect('chopp_list')
    faturamento = eh_faturamento(request.user)
    pedido = get_object_or_404(SolicitacaoChopp, pk=pk) if faturamento else _pedido_visivel_ou_404(request.user, pk)
    if not (faturamento or pode_editar_como_vendedor(request.user, pedido)):
        messages.error(request, "Você não pode cancelar este pedido.")
        return redirect('chopp_list')
    if pedido.status != 'PENDENTE':
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
    pedidos = SolicitacaoChopp.objects.select_related('vendedor', 'usuario_faturamento').prefetch_related('itens')
    if request.GET.get('data_ini'):
        pedidos = pedidos.filter(data_solicitacao__date__gte=request.GET['data_ini'])
    if request.GET.get('data_fim'):
        pedidos = pedidos.filter(data_solicitacao__date__lte=request.GET['data_fim'])
    if request.GET.get('status'):
        pedidos = pedidos.filter(status=request.GET['status'])
    if request.GET.get('vendedor'):
        pedidos = pedidos.filter(vendedor_id=request.GET['vendedor'])

    linhas_excel = []
    for p in pedidos.order_by('data_solicitacao'):
        for it in p.itens.all():
            linhas_excel.append({
                'Pedido': p.id,
                'Data': timezone.localtime(p.data_solicitacao).replace(tzinfo=None),
                'Vendedor': p.vendedor.get_full_name() or p.vendedor.username,
                'Cliente': p.cliente_razao_social,
                'CPF/CNPJ': p.cliente_cpf_cnpj,
                'Código/Loja': f"{p.cliente_codigo}/{p.cliente_loja}",
                'Recebimento': p.get_recebimento_display(),
                'Data de entrega': p.data_entrega or '',
                'Prazo solicitado': p.get_prazo_pagamento_solicitado_display() or p.get_prazo_pagamento_display(),
                'Prazo final': p.get_prazo_pagamento_display(),
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


@grupo_requerido(*CHOPP_ACESSO, json=True)
def api_busca_produtos_chopp(request):
    """Produtos dos grupos de chopp, sem preço (o vendedor informa o preço)."""
    termo = (request.GET.get('q') or '').upper().strip()
    if len(termo) < 3:
        return JsonResponse([], safe=False)
    marcadores = ', '.join(['%s'] * len(GRUPOS_PRODUTO_CHOPP))
    query = (
        "SELECT SB1.B1_COD, SB1.B1_DESC, ISNULL(SBM.BM_DESC, 'SEM GRUPO') AS BM_DESC "
        "FROM {tabela} AS SB1 "
        "LEFT JOIN SBM{empresa} AS SBM ON RTRIM(SBM.BM_GRUPO) = RTRIM(SB1.B1_GRUPO) AND SBM.D_E_L_E_T_ <> '*' "
        "WHERE SB1.D_E_L_E_T_ <> '*' AND SB1.B1_MSBLQL <> '1' "
        "AND SB1.B1_FILIAL = %s "
        f"AND RTRIM(SB1.B1_GRUPO) IN ({marcadores}) "
        "AND (SB1.B1_DESC LIKE %s OR SB1.B1_COD LIKE %s)"
    )
    # Produtos de chopp: só base CIEC, tabela SB1010, filial 0101
    bases = {'protheus_ciec': ['SB1010']}
    try:
        resultados = consultar(bases, query, [FILIAL_PRODUTO_CHOPP] + GRUPOS_PRODUTO_CHOPP + [f'%{termo}%', f'%{termo}%'])
    except ProtheusIndisponivel:
        return JsonResponse({'erro': 'Não foi possível consultar o Protheus agora. Tente novamente em instantes.'}, status=503)
    produtos = {}
    for row in linhas(resultados):
        codigo = str(row[0]).strip()
        if codigo not in produtos:
            produtos[codigo] = {'codigo': codigo, 'descricao': str(row[1]).strip(), 'grupo_familia': str(row[2]).strip()}
    return JsonResponse(list(produtos.values()), safe=False)
