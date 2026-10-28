"""
Agendamento de retirada de chopp (coluna de pendentes + hoje e os próximos 6 dias, sem domingo).

- Vendedor: grava o pedido sem dia (PENDENTE); edita e cancela os seus enquanto PENDENTE ou AGENDADO.
  Vê os seus pendentes e os já agendados.
- Gestão Comercial (backoffice): distribui os pedidos entre os dias com hora livre (AGENDADO), remarca,
  devolve para pendentes, edita e cancela; confirma o dia (AGENDADO -> ENVIADO). Depois do dia
  confirmado só ela altera ou inclui pedidos no dia (entram direto como ENVIADO), nunca com hora já passada.

Cliente, condição de pagamento, tabela e preço vêm sempre do Protheus (CIEC 01, filial 0101):
o que chega da tela só identifica o cliente e os produtos; o resto é consultado de novo ao salvar.

Inadimplência: só alerta (cartão, detalhes, confirmação e formulário); não bloqueia nada.
PDF do dia confirmado: lista para a fábrica, sem preços, com total por produto.
"""
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from app.permissoes import grupo_requerido, no_grupo
from app.protheus import ProtheusIndisponivel

from . import protheus_chopp
from .models import DiaConfirmadoChopp, SolicitacaoChopp, SolicitacaoChoppItem

logger = logging.getLogger(__name__)

GESTAO_AGENDAMENTO = ('Gestão Comercial',)
AGENDAMENTO_ACESSO = ('Vendedores',) + GESTAO_AGENDAMENTO
# títulos vencidos também aparecem para quem trabalha na tela do Chopp
TITULOS_ACESSO = AGENDAMENTO_ACESSO + ('Faturamento', 'Gestão Financeira')

DIAS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']
# status em que o pedido ainda pode ser mexido no calendário
ALTERA_VENDEDOR = ('PENDENTE', 'AGENDADO')
ALTERA_GESTAO = ('PENDENTE', 'AGENDADO', 'ENVIADO')

MSG_PROTHEUS = "Não foi possível consultar o Protheus agora. Tente novamente em instantes."


# ------------------------------------------------------------------ regras de data e horário
def hoje():
    return timezone.localdate()


def segunda_da_semana(dia):
    return dia - timedelta(days=dia.weekday())


DIAS_NO_CALENDARIO = 7


def dias_calendario(referencia=None):
    """Hoje e os próximos dias até completar 7 colunas, pulando o domingo."""
    dia, dias = referencia or hoje(), []
    while len(dias) < DIAS_NO_CALENDARIO:
        if dia.weekday() != 6:
            dias.append(dia)
        dia += timedelta(days=1)
    return dias


def periodo_calendario(referencia=None):
    """(primeiro dia, último dia) do calendário."""
    dias = dias_calendario(referencia)
    return dias[0], dias[-1]


def proximo_dia_util(dia=None):
    """Dia seguinte, pulando o domingo (no sábado, é a segunda)."""
    proximo = (dia or hoje()) + timedelta(days=1)
    return proximo + timedelta(days=1) if proximo.weekday() == 6 else proximo


def dia_confirmado(dia):
    return DiaConfirmadoChopp.objects.filter(data=dia).exists()


def data_aceita_agendamento(dia, gestao=False):
    """Dias do calendário (hoje + 6, sem domingo); dia já confirmado só para a gestão."""
    _, fim = periodo_calendario()
    return hoje() <= dia <= fim and dia.weekday() != 6 and (gestao or not dia_confirmado(dia))


def validar_agenda(dia, hora, gestao):
    """Erros de dia/hora para agendar (lista vazia = ok). Hora livre, mas nunca já passada hoje."""
    erros = []
    if dia is None or hora is None:
        return ["Informe o dia e a hora da retirada."]
    if dia.weekday() == 6:
        erros.append("Não há retirada aos domingos.")
    elif not data_aceita_agendamento(dia, gestao):
        if dia_confirmado(dia) and not gestao:
            erros.append(f"O dia {dia:%d/%m} já foi confirmado.")
        else:
            inicio, fim = periodo_calendario()
            erros.append(f"O dia da retirada deve ser entre {inicio:%d/%m} e {fim:%d/%m}.")
    if dia == hoje() and hora < timezone.localtime().time().replace(second=0, microsecond=0):
        erros.append(f"A hora não pode ser anterior à hora atual ({timezone.localtime():%H:%M}).")
    return erros


def status_do_dia(dia):
    """Agendar num dia já confirmado manda o pedido direto como ENVIADO."""
    return 'ENVIADO' if dia_confirmado(dia) else 'AGENDADO'


def pode_confirmar_dia(user, dia, pendentes):
    """Gestão Comercial; próximo dia útil ou anterior; precisa ter agendamento pendente."""
    return eh_gestao(user) and pendentes > 0 and dia <= proximo_dia_util()


# ------------------------------------------------------------------ inadimplência (só alerta)
def _limite_vencimento():
    """Títulos com vencimento real antes desta data estão em atraso além da tolerância."""
    return hoje() - timedelta(days=settings.INADIMPLENCIA_DIAS_ATRASO)


def inadimplencia_dos_clientes(pares):
    """
    {(codigo, loja): {'titulos', 'valor', 'vencimento', 'dias'}} dos inadimplentes entre os pares informados.
    Consulta o Protheus a cada carregamento da página (pagamentos baixam na hora).
    Se o Protheus estiver fora, devolve None (a tela avisa que não conseguiu verificar).
    """
    pares = {(str(c).strip(), str(l).strip()) for c, l in pares}
    if not pares:
        return {}
    try:
        novos = protheus_chopp.inadimplencia(pares, _limite_vencimento())
    except ProtheusIndisponivel as e:
        logger.error("Inadimplência não verificada: %s", e)
        return None
    resultado = {}
    for par in pares:
        info = novos.get(par)
        if info and float(info['valor']) >= settings.INADIMPLENCIA_VALOR_MINIMO:
            info['dias'] = (hoje() - info['vencimento']).days if info['vencimento'] else None
            resultado[par] = info
    return resultado


# ------------------------------------------------------------------ permissões
def eh_gestao(user):
    return no_grupo(user, *GESTAO_AGENDAMENTO)


def agendamentos_visiveis(user):
    qs = SolicitacaoChopp.objects.select_related('vendedor').prefetch_related('itens')
    return qs if eh_gestao(user) else qs.filter(vendedor=user)


def pode_alterar(user, ag):
    """Vendedor: os seus, pendentes ou agendados. Gestão: qualquer um até o dia ser entregue."""
    if eh_gestao(user):
        return ag.status in ALTERA_GESTAO
    return ag.status in ALTERA_VENDEDOR and ag.vendedor_id == user.id


def _agendamento_ou_404(user, pk):
    ag = agendamentos_visiveis(user).filter(pk=pk).first()
    if not ag:
        raise Http404("Agendamento não encontrado.")
    return ag


# ------------------------------------------------------------------ formulário
def _decimal(valor):
    texto = str(valor or '').strip().replace('R$', '').replace(' ', '')
    if ',' in texto:
        texto = texto.replace('.', '').replace(',', '.')
    try:
        return Decimal(texto).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def _ler_formulario(request, gestao=False, atual=None):
    """
    Valida o pedido e completa com o Protheus.
    Retorna (dados, itens, erros). Itens: [{codigo, nome, qtd, preco, da_tabela}].
    A gestão pode informar dia e hora já no formulário (dados['agenda'] = (dia, hora) ou None).
    """
    p = request.POST
    erros = []
    codigo, loja = (p.get('cliente_codigo') or '').strip(), (p.get('cliente_loja') or '').strip()

    agenda = None
    if gestao and (p.get('data_retirada') or p.get('hora_retirada')):
        dia = hora = None
        try:
            dia = datetime.strptime(p.get('data_retirada') or '', '%Y-%m-%d').date()
            hora = datetime.strptime(p.get('hora_retirada') or '', '%H:%M').time()
        except ValueError:
            erros.append("Para agendar já, informe o dia e a hora (ou deixe os dois em branco).")
        else:
            if (dia, hora) != atual:    # dia/hora que já estavam gravados continuam valendo
                erros += validar_agenda(dia, hora, gestao=True)
            agenda = (dia, hora)

    # itens informados
    indices = sorted({k.rsplit('_', 1)[-1] for k in p if k.startswith('item_codigo_')}, key=lambda i: int(i) if i.isdigit() else 0)
    informados = []
    for i in indices:
        cod = (p.get(f'item_codigo_{i}') or '').strip()
        if not cod:
            continue
        try:
            qtd = int(p.get(f'item_qtd_{i}') or 0)
        except ValueError:
            qtd = 0
        informados.append({'codigo': cod, 'nome': (p.get(f'item_nome_{i}') or '').strip(), 'qtd': qtd,
                           'preco_tela': _decimal(p.get(f'item_preco_{i}'))})
    if not informados:
        erros.append("Inclua pelo menos um produto.")
    if len({it['codigo'] for it in informados}) != len(informados):
        erros.append("O mesmo produto foi incluído mais de uma vez.")
    for it in informados:
        if it['qtd'] <= 0:
            erros.append(f"Quantidade inválida para '{it['nome'] or it['codigo']}'.")

    if not codigo:
        erros.append("Selecione o cliente pela busca do Protheus.")
    if erros:
        return None, [], erros

    # Protheus: cliente, condição, tabela, produtos e preços
    try:
        cli = protheus_chopp.cliente(codigo, loja)
        if cli is None:
            return None, [], ["Cliente não encontrado no Protheus (CIEC, filial 0101) ou bloqueado."]
        if not cli['condicao']:
            return None, [], ["Cliente sem condição de pagamento no Protheus. Peça o ajuste do cadastro antes de agendar."]
        validos = protheus_chopp.produtos_validos([it['codigo'] for it in informados])
        precos = protheus_chopp.precos_tabela(cli['tabela'], list(validos))
    except ProtheusIndisponivel as e:
        logger.error("Agendamento não gravado: %s", e)
        return None, [], [MSG_PROTHEUS]

    itens = []
    for it in informados:
        produto = validos.get(it['codigo'])
        if not produto:
            erros.append(f"O produto {it['codigo']} não é um produto de chopp ativo no Protheus.")
            continue
        preco = precos.get(it['codigo'])
        da_tabela = preco is not None
        if not da_tabela:
            preco = it['preco_tela']
            if preco is None or preco <= 0:
                erros.append(f"'{produto['descricao']}' não está na tabela de preço do cliente: informe o preço.")
                continue
        itens.append({'codigo': it['codigo'], 'nome': produto['descricao'], 'qtd': it['qtd'], 'preco': preco, 'da_tabela': da_tabela})

    dados = {
        'cliente_codigo': cli['codigo'], 'cliente_loja': cli['loja'],
        'cliente_razao_social': cli['nome'][:100], 'cliente_nome_fantasia': cli['fantasia'][:100],
        'cliente_cpf_cnpj': cli['cnpj'][:18],
        'condicao_pagamento': cli['condicao'][:10],
        'condicao_pagamento_descricao': (cli['condicao_descricao'] or cli['condicao'])[:60],
        'tabela_preco': cli['tabela'][:10],
        'observacao': (p.get('observacao') or '').strip(),
        'agenda': agenda,
    }
    return dados, itens, erros


def _gravar_itens(ag, itens):
    ag.itens.all().delete()
    for it in itens:
        SolicitacaoChoppItem.objects.create(
            solicitacao=ag, produto_codigo=it['codigo'], produto_descricao=it['nome'][:100],
            quantidade=it['qtd'], preco_unitario=it['preco'],
            qtd_solicitada=it['qtd'], preco_solicitado=it['preco'], preco_da_tabela=it['da_tabela'])


def _estado(ag=None, post=None):
    """Valores para preencher o formulário (do POST com erro ou do agendamento salvo)."""
    if post is not None:
        indices = sorted({k.rsplit('_', 1)[-1] for k in post if k.startswith('item_codigo_')}, key=lambda i: int(i) if i.isdigit() else 0)
        return {
            'cliente': {k: post.get(f'cliente_{k}', '') for k in
                        ('codigo', 'loja', 'nome', 'fantasia', 'cnpj', 'condicao', 'condicao_descricao', 'tabela')},
            'data_retirada': post.get('data_retirada', ''), 'hora_retirada': post.get('hora_retirada', ''),
            'observacao': post.get('observacao', ''),
            'itens': [{'codigo': post.get(f'item_codigo_{i}', ''), 'nome': post.get(f'item_nome_{i}', ''),
                       'qtd': post.get(f'item_qtd_{i}', ''), 'preco': post.get(f'item_preco_{i}', ''),
                       'da_tabela': post.get(f'item_da_tabela_{i}') == '1'} for i in indices],
        }
    if ag is None:
        return {'cliente': None, 'data_retirada': '', 'hora_retirada': '', 'observacao': '', 'itens': []}
    return {
        'cliente': {'codigo': ag.cliente_codigo, 'loja': ag.cliente_loja, 'nome': ag.cliente_razao_social,
                    'fantasia': ag.cliente_nome_fantasia, 'cnpj': ag.cliente_cpf_cnpj, 'condicao': ag.condicao_pagamento,
                    'condicao_descricao': ag.condicao_pagamento_descricao, 'tabela': ag.tabela_preco},
        'data_retirada': ag.data_retirada.isoformat() if ag.data_retirada else '', 'hora_retirada': ag.horario,
        'observacao': ag.observacao,
        'itens': [{'codigo': i.produto_codigo, 'nome': i.produto_descricao, 'qtd': i.quantidade,
                   'preco': str(i.preco_unitario), 'da_tabela': i.preco_da_tabela} for i in ag.itens.all()],
    }


def _opcoes_de_dia():
    """Dias do calendário para os seletores de agenda (marca os já confirmados)."""
    confirmados = set(DiaConfirmadoChopp.objects.filter(data__range=periodo_calendario()).values_list('data', flat=True))
    return [{'valor': d.isoformat(), 'rotulo': f"{DIAS[d.weekday()]}, {d:%d/%m}" + (" · confirmado" if d in confirmados else ""),
             'confirmado': d in confirmados} for d in dias_calendario()]


def _contexto_form(titulo, ag=None, post=None, gestao=False, data_inicial=''):
    estado = _estado(ag, post)
    if data_inicial and not estado['data_retirada']:
        estado['data_retirada'] = data_inicial
    return {
        'titulo': titulo, 'agendamento': ag, 'estado': estado,
        'eh_gestao': gestao, 'opcoes_dia': _opcoes_de_dia() if gestao else [],
    }


# ------------------------------------------------------------------ telas
@never_cache   # inadimplência sempre do Protheus, sem o navegador reaproveitar a página
@grupo_requerido(*AGENDAMENTO_ACESSO)
def agendamento_calendario(request):
    gestao = eh_gestao(request.user)
    datas = dias_calendario()
    inicio, fim = datas[0], datas[-1]

    visiveis = agendamentos_visiveis(request.user)
    vendedor_id = request.GET.get('vendedor') if gestao else None
    if vendedor_id:
        visiveis = visiveis.filter(vendedor_id=vendedor_id)
    ags = visiveis.filter(data_retirada__range=(inicio, fim))
    pedidos_pendentes = list(visiveis.filter(status='PENDENTE').order_by('data_solicitacao', 'id'))

    por_dia = {}
    for ag in ags.order_by('hora_retirada', 'cliente_razao_social'):
        por_dia.setdefault(ag.data_retirada, []).append(ag)
    confirmados = {c.data: c for c in DiaConfirmadoChopp.objects.filter(data__range=(inicio, fim)).select_related('confirmado_por')}
    # agendados (ainda não enviados) de todos os vendedores: a confirmação vale para o dia inteiro, mesmo com filtro;
    # inclui dias anteriores que ficaram sem confirmar (aparecem num aviso acima do calendário)
    a_confirmar = {}
    for a in SolicitacaoChopp.objects.filter(data_retirada__lte=fim, status='AGENDADO').select_related('vendedor').prefetch_related('itens'):
        a_confirmar.setdefault(a.data_retirada, []).append(a)

    ativos = [a for lista in por_dia.values() for a in lista if a.status in ('AGENDADO', 'ENVIADO', 'ENTREGUE')]
    ativos += pedidos_pendentes + [a for lista in a_confirmar.values() for a in lista]
    inad = inadimplencia_dos_clientes({(a.cliente_codigo, a.cliente_loja) for a in ativos})
    for a in ativos:
        a.inadimplencia = (inad or {}).get((a.cliente_codigo.strip(), a.cliente_loja.strip()))

    dias = []
    for dia in datas:
        lista = por_dia.get(dia, [])
        validos = [a for a in lista if a.status != 'CANCELADO']
        pendentes = a_confirmar.get(dia, [])
        dias.append({
            'data': dia, 'nome': DIAS[dia.weekday()],
            'eh_hoje': dia == hoje(), 'passado': dia < hoje(),
            'confirmado': confirmados.get(dia),
            'pode_confirmar': pode_confirmar_dia(request.user, dia, len(pendentes)),
            'pendentes': pendentes,
            'pendentes_unidades': sum(i.quantidade for a in pendentes for i in a.itens.all()),
            'pendentes_litros': sum(a.litros for a in pendentes),
            'pode_incluir': gestao and data_aceita_agendamento(dia, gestao=True),
            'agendamentos': lista,
            'qtd_agendamentos': len(validos),
            'qtd_unidades': sum(i.quantidade for a in validos for i in a.itens.all()),
            'litros': sum(a.litros for a in validos),
        })

    # dias que já passaram e ainda têm agendamento sem confirmar (só a gestão confirma)
    atrasados = []
    for dia in sorted(d for d in a_confirmar if d < inicio):
        pendentes = a_confirmar[dia]
        atrasados.append({
            'data': dia, 'nome': DIAS[dia.weekday()],
            'pendentes': pendentes, 'pendentes_unidades': sum(i.quantidade for a in pendentes for i in a.itens.all()),
            'pendentes_litros': sum(a.litros for a in pendentes),
            'pode_confirmar': pode_confirmar_dia(request.user, dia, len(pendentes)),
        })

    alteraveis = [a for lista in por_dia.values() for a in lista] + pedidos_pendentes
    return render(request, 'solicitacoes/agendamento_calendario.html', {
        'dias': dias, 'inicio': inicio, 'fim': fim,
        'pedidos_pendentes': pedidos_pendentes,
        'litros_pendentes': sum(a.litros for a in pedidos_pendentes),
        'litros_agendados': sum(d['litros'] for d in dias),
        'atrasados': atrasados if gestao else [],
        'dias_confirmacao': dias + (atrasados if gestao else []),
        'eh_gestao': gestao,
        'opcoes_dia': _opcoes_de_dia() if gestao else [],
        'vendedores': User.objects.filter(groups__name='Vendedores', is_active=True).distinct().order_by('first_name') if gestao else [],
        'vendedor_id': vendedor_id or '',
        'pode_alterar_ids': {a.id for a in alteraveis if pode_alterar(request.user, a)},
        'inadimplencia_indisponivel': inad is None,
        'pdf_dia': request.session.pop('agendamento_pdf_dia', None),
    })


@grupo_requerido(*GESTAO_AGENDAMENTO, destino='agendamento_calendario')
def agendamento_agendar(request, pk):
    """Backoffice define (ou remarca) dia e hora, ou devolve o pedido para os pendentes."""
    ag = _agendamento_ou_404(request.user, pk)
    if request.method != 'POST':
        return redirect(_url_calendario(ag.data_retirada))
    if ag.status not in ALTERA_GESTAO:
        messages.error(request, f"O pedido #{ag.id} está {ag.get_status_display().lower()} e não pode mais ser remarcado.")
        return redirect(_url_calendario(ag.data_retirada))

    if request.POST.get('acao') == 'pendente':
        with transaction.atomic():
            ag = SolicitacaoChopp.objects.select_for_update().get(pk=ag.pk)
            if ag.status not in ALTERA_GESTAO:
                messages.error(request, "O pedido mudou de situação enquanto você alterava.")
                return redirect(_url_calendario(None))
            ag.status, ag.data_retirada, ag.hora_retirada = 'PENDENTE', None, None
            ag.agendado_por, ag.agendado_em = None, None
            ag.save()
        messages.success(request, f"Pedido #{ag.id} voltou para os pendentes.")
        return redirect(_url_calendario(None))

    try:
        dia = date.fromisoformat(request.POST.get('data_retirada') or '')
        hora = datetime.strptime(request.POST.get('hora_retirada') or '', '%H:%M').time()
    except ValueError:
        dia = hora = None
    erros = validar_agenda(dia, hora, gestao=True)
    if erros:
        for e in erros:
            messages.error(request, e)
        return redirect(_url_calendario(ag.data_retirada))
    with transaction.atomic():
        ag = SolicitacaoChopp.objects.select_for_update().get(pk=ag.pk)
        if ag.status not in ALTERA_GESTAO:
            messages.error(request, "O pedido mudou de situação enquanto você alterava.")
            return redirect(_url_calendario(dia))
        ag.data_retirada, ag.hora_retirada = dia, hora
        ag.status = status_do_dia(dia)
        ag.agendado_por, ag.agendado_em = request.user, timezone.now()
        ag.save()
    extra = " Dia já confirmado: o pedido foi direto como Enviado." if ag.status == 'ENVIADO' else ""
    messages.success(request, f"Pedido #{ag.id} ({ag.cliente_nome}) agendado para {dia:%d/%m} às {ag.horario}.{extra}")
    return redirect(_url_calendario(dia))


@grupo_requerido(*GESTAO_AGENDAMENTO, destino='agendamento_calendario')
def agendamento_confirmar_dia(request, data):
    """Envia os agendamentos pendentes do dia (AGENDADO -> ENVIADO) e trava o dia."""
    try:
        dia = date.fromisoformat(data)
    except ValueError:
        raise Http404("Data inválida.")
    if request.method != 'POST':
        return redirect(_url_calendario(dia))
    if dia > proximo_dia_util():
        messages.error(request, f"Só é possível confirmar até {proximo_dia_util():%d/%m} (próximo dia útil).")
        return redirect(_url_calendario(dia))

    with transaction.atomic():
        pendentes = list(SolicitacaoChopp.objects.select_for_update().filter(data_retirada=dia, status='AGENDADO'))
        if not pendentes:
            messages.error(request, f"Não há agendamentos pendentes em {dia:%d/%m}.")
            return redirect(_url_calendario(dia))
        DiaConfirmadoChopp.objects.get_or_create(data=dia, defaults={'confirmado_por': request.user})
        SolicitacaoChopp.objects.filter(pk__in=[a.pk for a in pendentes]).update(status='ENVIADO')

    messages.success(request, f"Dia {dia:%d/%m} confirmado: {len(pendentes)} agendamento(s) enviado(s) para o Faturamento.")
    request.session['agendamento_pdf_dia'] = dia.isoformat()   # o calendário abre o PDF do dia
    return redirect(_url_calendario(dia))


@grupo_requerido(*GESTAO_AGENDAMENTO, destino='agendamento_calendario')
def agendamento_pdf_dia(request, data):
    """Lista do dia confirmado para a fábrica: sem preços, com total por produto."""
    try:
        dia = date.fromisoformat(data)
    except ValueError:
        raise Http404("Data inválida.")
    confirmacao = DiaConfirmadoChopp.objects.filter(data=dia).select_related('confirmado_por').first()
    if not confirmacao:
        messages.error(request, f"O dia {dia:%d/%m} ainda não foi confirmado.")
        return redirect(_url_calendario(dia))

    retiradas = list(SolicitacaoChopp.objects.filter(data_retirada=dia).exclude(status__in=['PENDENTE', 'AGENDADO', 'CANCELADO'])
                     .select_related('vendedor').prefetch_related('itens').order_by('hora_retirada', 'cliente_razao_social'))
    # O PDF é o que foi confirmado para a fábrica: itens e quantidades agendados (ajustes do Faturamento não entram)
    totais = {}
    for a in retiradas:
        a.itens_agendados = [i for i in a.itens.all() if i.qtd_solicitada is not None]
        for i in a.itens_agendados:
            t = totais.setdefault(i.produto_codigo, {'codigo': i.produto_codigo, 'descricao': i.produto_descricao, 'quantidade': 0})
            t['quantidade'] += i.qtd_solicitada

    from xhtml2pdf import pisa
    from .views import _registrar_fonte_pdf
    _registrar_fonte_pdf()
    html = render_to_string('solicitacoes/agendamento_pdf.html', {
        'dia': dia, 'nome_dia': DIAS[dia.weekday()] if dia.weekday() < 6 else 'Domingo',
        'confirmacao': confirmacao, 'retiradas': retiradas,
        'totais': sorted(totais.values(), key=lambda t: t['descricao']),
        'total_unidades': sum(t['quantidade'] for t in totais.values()),
        'gerado_em': timezone.localtime(),
    })
    resposta = HttpResponse(content_type='application/pdf')
    resposta['Content-Disposition'] = f'inline; filename="retiradas_chopp_{dia:%Y%m%d}.pdf"'
    if pisa.CreatePDF(html, dest=resposta).err:
        return HttpResponse('Erro ao gerar PDF', status=500)
    return resposta


def _aplicar_agenda(ag, agenda, user):
    """Grava dia/hora vindos do formulário da gestão (ou mantém como está quando não veio agenda)."""
    if agenda:
        ag.data_retirada, ag.hora_retirada = agenda
        ag.status = status_do_dia(agenda[0])
        ag.agendado_por, ag.agendado_em = user, timezone.now()


@grupo_requerido(*AGENDAMENTO_ACESSO)
def agendamento_novo(request):
    gestao = eh_gestao(request.user)
    if request.method == 'POST':
        dados, itens, erros = _ler_formulario(request, gestao=gestao)
        if erros:
            for e in erros:
                messages.error(request, e)
            return render(request, 'solicitacoes/agendamento_form.html', _contexto_form('Novo Pedido de Chopp', post=request.POST, gestao=gestao))
        agenda = dados.pop('agenda')
        with transaction.atomic():
            ag = SolicitacaoChopp(vendedor=request.user, status='PENDENTE', **dados)
            _aplicar_agenda(ag, agenda, request.user)
            ag.save()
            _gravar_itens(ag, itens)
        if ag.status == 'PENDENTE':
            messages.success(request, f"Pedido #{ag.id} gravado. Ele fica nos pendentes até o backoffice definir o dia e a hora.")
        else:
            messages.success(request, f"Pedido #{ag.id} agendado para {ag.data_retirada:%d/%m} às {ag.horario}.")
        return redirect(_url_calendario(ag.data_retirada))

    data_inicial = request.GET.get('data', '') if gestao else ''
    try:
        if data_inicial and not data_aceita_agendamento(date.fromisoformat(data_inicial), gestao=True):
            data_inicial = ''
    except ValueError:
        data_inicial = ''
    return render(request, 'solicitacoes/agendamento_form.html', _contexto_form('Novo Pedido de Chopp', gestao=gestao, data_inicial=data_inicial))


@grupo_requerido(*AGENDAMENTO_ACESSO)
def agendamento_editar(request, pk):
    gestao = eh_gestao(request.user)
    ag = _agendamento_ou_404(request.user, pk)
    if not pode_alterar(request.user, ag):
        messages.error(request, f"O pedido #{ag.id} está {ag.get_status_display().lower()} e não pode mais ser alterado.")
        return redirect(_url_calendario(ag.data_retirada))

    if request.method == 'POST':
        dados, itens, erros = _ler_formulario(request, gestao=gestao, atual=(ag.data_retirada, ag.hora_retirada))
        agenda = dados.pop('agenda') if dados else None
        # a gestão pode deixar dia/hora como estavam (hora já passada hoje continua valendo se não mudou)
        if gestao and agenda and agenda == (ag.data_retirada, ag.hora_retirada):
            agenda = None
        if gestao and not erros and agenda is None and not request.POST.get('data_retirada') and ag.data_retirada:
            erros.append("Para tirar o pedido do dia, use \"Voltar para pendentes\" no calendário.")
        if erros:
            for e in erros:
                messages.error(request, e)
            return render(request, 'solicitacoes/agendamento_form.html', _contexto_form(f'Editar Pedido #{ag.id}', ag, request.POST, gestao=gestao))
        with transaction.atomic():
            ag = SolicitacaoChopp.objects.select_for_update().get(pk=ag.pk)
            if not pode_alterar(request.user, ag):
                messages.error(request, "O pedido mudou de situação enquanto você editava; a alteração não foi salva.")
                return redirect(_url_calendario(ag.data_retirada))
            for campo, valor in dados.items():
                setattr(ag, campo, valor)
            _aplicar_agenda(ag, agenda, request.user)
            ag.save()
            _gravar_itens(ag, itens)
        messages.success(request, f"Pedido #{ag.id} atualizado.")
        return redirect(_url_calendario(ag.data_retirada))

    return render(request, 'solicitacoes/agendamento_form.html', _contexto_form(f'Editar Pedido #{ag.id}', ag, gestao=gestao))


@grupo_requerido(*AGENDAMENTO_ACESSO)
def agendamento_cancelar(request, pk):
    ag = _agendamento_ou_404(request.user, pk)
    if request.method != 'POST':
        return redirect(_url_calendario(ag.data_retirada))
    if not pode_alterar(request.user, ag):
        messages.error(request, f"O pedido #{ag.id} está {ag.get_status_display().lower()} e não pode ser cancelado aqui.")
        return redirect(_url_calendario(ag.data_retirada))
    motivo = (request.POST.get('motivo') or '').strip()
    if not motivo:
        messages.error(request, "Informe o motivo do cancelamento.")
        return redirect(_url_calendario(ag.data_retirada))
    with transaction.atomic():
        ag = SolicitacaoChopp.objects.select_for_update().get(pk=ag.pk)
        if not pode_alterar(request.user, ag):
            messages.error(request, "O pedido mudou de situação e não pode mais ser cancelado aqui.")
            return redirect(_url_calendario(ag.data_retirada))
        ag.status = 'CANCELADO'
        ag.motivo_cancelamento = motivo
        ag.cancelado_por = request.user
        ag.data_cancelamento = timezone.now()
        ag.save()
    messages.success(request, f"Pedido #{ag.id} cancelado.")
    return redirect(_url_calendario(ag.data_retirada))


def _url_calendario(dia):
    """Volta para o calendário (todos os dias aparecem numa tela só)."""
    from django.urls import reverse
    return reverse('agendamento_calendario')


# ------------------------------------------------------------------ APIs do formulário
@never_cache   # inadimplência sempre do Protheus, sem o navegador reaproveitar a página
@grupo_requerido(*TITULOS_ACESSO, json=True)
def api_titulos(request):
    """Títulos vencidos do cliente (número, vencimento e valor), abertos ao clicar no alerta de inadimplência."""
    codigo, loja = (request.GET.get('codigo') or '').strip(), (request.GET.get('loja') or '').strip()
    if not codigo:
        return JsonResponse([], safe=False)
    try:
        titulos = protheus_chopp.titulos_vencidos(codigo, loja, _limite_vencimento())
    except ProtheusIndisponivel:
        return JsonResponse({'erro': 'Não foi possível consultar os títulos no Protheus agora.'}, status=503)
    return JsonResponse([{
        'empresa': t['empresa'],
        'titulo': '-'.join(p for p in (t['prefixo'], t['numero'], t['parcela']) if p),
        'tipo': t['tipo'],
        'emissao': t['emissao'].strftime('%d/%m/%Y') if t['emissao'] else '',
        'vencimento': t['vencimento'].strftime('%d/%m/%Y') if t['vencimento'] else '',
        'dias': (hoje() - t['vencimento']).days if t['vencimento'] else None,
        'valor': str(t['valor']),
        'saldo': str(t['saldo']),
    } for t in titulos], safe=False)


@never_cache   # inadimplência sempre do Protheus, sem o navegador reaproveitar a página
@grupo_requerido(*AGENDAMENTO_ACESSO, json=True)
def api_inadimplencia(request):
    codigo, loja = (request.GET.get('codigo') or '').strip(), (request.GET.get('loja') or '').strip()
    if not codigo:
        return JsonResponse({'inadimplente': False})
    inad = inadimplencia_dos_clientes({(codigo, loja)})
    if inad is None:
        return JsonResponse({'erro': 'Não foi possível verificar a inadimplência no Protheus agora.'}, status=503)
    info = inad.get((codigo, loja))
    if not info:
        return JsonResponse({'inadimplente': False})
    return JsonResponse({'inadimplente': True, 'titulos': info['titulos'], 'valor': str(info['valor']), 'dias': info['dias']})


@grupo_requerido(*AGENDAMENTO_ACESSO, json=True)
def api_clientes(request):
    try:
        return JsonResponse(protheus_chopp.buscar_clientes(request.GET.get('q')), safe=False)
    except ProtheusIndisponivel:
        return JsonResponse({'erro': MSG_PROTHEUS}, status=503)


@grupo_requerido(*AGENDAMENTO_ACESSO, json=True)
def api_produtos(request):
    """Produtos de chopp com o preço da tabela do cliente (preco = null quando não está na tabela)."""
    try:
        produtos = protheus_chopp.buscar_produtos(request.GET.get('q'))
        precos = protheus_chopp.precos_tabela(request.GET.get('tabela'), [p['codigo'] for p in produtos])
    except ProtheusIndisponivel:
        return JsonResponse({'erro': MSG_PROTHEUS}, status=503)
    for p in produtos:
        preco = precos.get(p['codigo'])
        p['preco'] = str(preco) if preco is not None else None
    return JsonResponse(produtos, safe=False)
