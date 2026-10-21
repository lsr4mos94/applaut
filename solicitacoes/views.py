import os
import base64
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
import pandas as pd
import requests
from xhtml2pdf import pisa
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404, JsonResponse
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import transaction, connections
from django.db.models import Sum, Q
from django.utils import timezone
from django.utils.html import strip_tags
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from .models import Plantao, Bonificacao, BonificacaoItem, FotoBonificacao
from .services import buscar_cliente_protheus_unificado, buscar_precos_protheus, buscar_produtos_protheus
from app.protheus import ProtheusIndisponivel
from django.core.cache import cache
from django.conf import settings
from cadastros.models import VerbaMensal, AcordoComercial, STATUS_QUE_CONSOMEM_VERBA
from app.permissoes import (
    grupo_requerido, no_grupo, GESTAO_COMERCIAL, FATURAMENTO, PLANTAO_ACESSO, PLANTAO_EQUIPE,
    eh_somente_vendedor, pode_ver_bonificacao,
)

# Copo brinde: vai junto com o chopp e não tem custo na bonificação
CODIGO_COPO_BRINDE = '000072'

# Pasta raiz dos boletos no servidor de arquivos (o download só aceita arquivos dentro dela)
PASTA_BOLETOS = r'\\SRV-FILESERVER\Faturamento\DOCUMENTOS FISCAIS'

logger = logging.getLogger(__name__)

def disparar_plantao_whatsapp(solicitacao):
    url = "https://api.zenvia.com/v2/channels/whatsapp/messages"
    if not settings.ZENVIA_API_TOKEN:
        logger.error("ZENVIA_API_TOKEN não configurado no .env; WhatsApp do plantão não enviado.")
        return {"sucesso": False, "erro": "Integração com WhatsApp não configurada."}
    headers = {
        "X-API-TOKEN": settings.ZENVIA_API_TOKEN,
        "Content-Type": "application/json"
    }
    
    endereco_completo = f"{solicitacao.endereco}, {solicitacao.numero}, {solicitacao.complemento}, {solicitacao.bairro} - {solicitacao.cidade}"

    payload = {
        "from": settings.ZENVIA_REMETENTE,
        "to": settings.ZENVIA_DESTINO_PLANTAO,
        "contents": [
            {
                "type": "template",
                "templateId": settings.ZENVIA_TEMPLATE_PLANTAO,
                "fields": {
                    "1": str(solicitacao.id),
                    "2": solicitacao.get_tipo_display(),
                    "3": solicitacao.nome_cliente,
                    "4": endereco_completo,
                    "5": solicitacao.get_ocorrencia_display(),
                    "6": solicitacao.horario.strftime('%H:%M') if solicitacao.horario else "",
                    "7": solicitacao.observacoes if solicitacao.observacoes else "Sem observações",
                }
            }
        ]
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        response_data = response.json()
        logger.info(f"Zenvia plantão #{solicitacao.id}: HTTP {response.status_code}")

        if response.status_code in [200, 201]:
            zenvia_id = response_data.get('id')
            if zenvia_id:
                solicitacao.zenvia_message_id = zenvia_id
                solicitacao.save()

            if response_data.get('status') == 'REJECTED':
                return {"sucesso": False, "erro": "Mensagem rejeitada pela operadora/Zenvia"}
            return {"sucesso": True, "data": response_data}
        else:
            erro_detalhado = response_data.get('details', [{}])[0].get('message', 'Erro de validação no Schema')
            return {"sucesso": False, "erro": f"{response_data.get('message')}: {erro_detalhado}"}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

@login_required
def api_busca_clientes(request):
    termo = request.GET.get('q', '')
    
    # O vendedor encontra qualquer cliente; o código dele não filtra a busca
    perfil = getattr(request.user, 'perfil', None)
    vendedor_cod = perfil.codigo_vendedor if perfil else None
    try:
        resultados = buscar_cliente_protheus_unificado(termo, vendedor_cod)
    except ProtheusIndisponivel:
        return JsonResponse({'erro': 'Não foi possível consultar o Protheus agora. Tente novamente em instantes.'}, status=503)
        
    return JsonResponse(resultados, safe=False)

@login_required
def buscar_produto_protheus_unificado(request):
    try:
        produtos = buscar_produtos_protheus(request.GET.get('q', ''))
    except ProtheusIndisponivel:
        return JsonResponse({'erro': 'Não foi possível consultar o Protheus agora. Tente novamente em instantes.'}, status=503)
    return JsonResponse(produtos, safe=False)

def _indice_boletos(forcar=False):
    """
    Lista dos PDFs dos últimos 90 dias nas pastas de boletos (ano atual e, se preciso, o anterior).
    Ler o servidor de arquivos inteiro é lento, então a lista fica guardada por 10 minutos.
    """
    chave = 'indice_boletos'
    if not forcar:
        indice = cache.get(chave)
        if indice is not None:
            return indice

    inicio_janela = datetime.now() - timedelta(days=90)
    anos = sorted({inicio_janela.year, datetime.now().year}, reverse=True)
    pastas = [p for p in (os.path.join(PASTA_BOLETOS, str(a)) for a in anos) if os.path.exists(p)]
    if not pastas:
        raise FileNotFoundError(PASTA_BOLETOS)

    limite = inicio_janela.timestamp()
    indice = []
    for pasta in pastas:
        for raiz, _, arquivos in os.walk(pasta):
            for nome in arquivos:
                if not nome.upper().endswith('.PDF'):
                    continue
                caminho = os.path.join(raiz, nome)
                try:
                    modificado = os.path.getmtime(caminho)
                except OSError:
                    continue
                if modificado >= limite:
                    indice.append((nome.upper(), nome, caminho, modificado))
    cache.set(chave, indice, 600)
    return indice


def _filtrar_boletos(indice, numero_nota):
    termo = numero_nota.upper()
    return [
        {'nome': nome, 'caminho': base64.urlsafe_b64encode(caminho.encode()).decode(), 'data': modificado}
        for nome_upper, nome, caminho, modificado in indice
        if termo in nome_upper
    ]


@login_required
def buscar_boleto(request):
    lista_boletos = []
    numero_nota = request.POST.get('numero_nota', '').strip()
    abrir_modal = False

    if request.method == 'POST' and numero_nota:
        try:
            indice = _indice_boletos()
            lista_boletos = _filtrar_boletos(indice, numero_nota)
            if not lista_boletos:
                # Boleto pode ter sido salvo depois da última leitura da pasta: lê de novo uma vez
                indice = _indice_boletos(forcar=True)
                lista_boletos = _filtrar_boletos(indice, numero_nota)
        except FileNotFoundError:
            logger.error(f"ERRO DE ACESSO: nenhuma pasta de boletos encontrada em {PASTA_BOLETOS}.")
            return render(request, 'solicitacoes/boletos.html', {
                'mensagem': 'O servidor de arquivos dos boletos está inacessível.',
                'tipo_mensagem': 'erro',
                'numero_nota': numero_nota
            })

        try:
            lista_boletos.sort(key=lambda x: x['data'], reverse=True)
            abrir_modal = True if lista_boletos else False

        except Exception as e:
            logger.exception("Erro grave durante a busca de arquivos:")
            return render(request, 'solicitacoes/boletos.html', {
                'mensagem': f'Erro interno: {str(e)}', 
                'tipo_mensagem': 'erro'
            })

    if request.method == 'POST' and not lista_boletos:
        return render(request, 'solicitacoes/boletos.html', {
            'mensagem': f'Boleto da nota "{numero_nota}" não encontrado nos últimos 90 dias.',
            'tipo_mensagem': 'erro',
            'numero_nota': numero_nota
        })

    return render(request, 'solicitacoes/boletos.html', {
        'lista_boletos': lista_boletos,
        'numero_nota': numero_nota,
        'abrir_modal': abrir_modal
    })

@login_required
def baixar_boleto(request, caminho_b64):
    try:
        caminho_real = base64.urlsafe_b64decode(caminho_b64.encode()).decode()

        # Só entrega PDFs que estejam dentro da pasta de boletos (bloqueia "../" e outros caminhos)
        raiz = os.path.normcase(os.path.realpath(PASTA_BOLETOS))
        alvo = os.path.normcase(os.path.realpath(caminho_real))
        try:
            dentro_da_pasta = os.path.commonpath([raiz, alvo]) == raiz
        except ValueError:
            dentro_da_pasta = False  # no Windows: caminho em outro disco
        if not dentro_da_pasta or not alvo.endswith('.pdf'):
            logger.warning(f"Download de boleto bloqueado: {caminho_real} (usuário {request.user})")
            raise Http404("Arquivo não encontrado.")

        if os.path.exists(caminho_real):
            with open(caminho_real, 'rb') as f:
                response = HttpResponse(f.read(), content_type='application/pdf')
                response['Content-Disposition'] = f'inline; filename="{os.path.basename(caminho_real)}"'
                return response
        else:
            raise Http404("Arquivo não encontrado no servidor.")
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Erro no download do boleto: {e}")
        raise Http404("Erro ao processar o arquivo.")

def _pode_alterar_plantao(user, plantao):
    """Quem criou o plantão ou a equipe de plantão."""
    return plantao.vendedor_id == user.id or no_grupo(user, *PLANTAO_EQUIPE)


@grupo_requerido(*PLANTAO_ACESSO)
def plantao_list(request):
    if request.method == 'POST' and 'plantao_id' in request.POST:
        if not no_grupo(request.user, *PLANTAO_EQUIPE):
            messages.error(request, "Você não tem permissão para confirmar plantões.")
            return redirect('plantao_list')
        plantao_id = request.POST.get('plantao_id')
        obs = request.POST.get('obs_confirmacao')
        plantao = get_object_or_404(Plantao, id=plantao_id)
        
        plantao.status = 'CONFIRMADO'
        if obs:
            atual_obs = plantao.observacoes or ""
            plantao.observacoes = f"{atual_obs}\n[CONFIRMAÇÃO]: {obs}".strip()
        
        plantao.save()
        messages.success(request, f"Plantão de {plantao.nome_cliente} confirmado!")
        
        return redirect(f"{request.path}?{request.GET.urlencode()}")

    busca = request.GET.get('busca')
    vendedor_id = request.GET.get('vendedor')
    ocorrencia = request.GET.get('ocorrencia')
    data_f = request.GET.get('data')
    page_number = request.GET.get('page')

    plantoes_list = Plantao.objects.all().order_by('-data_solicitacao', '-id')

    if busca:
        plantoes_list = plantoes_list.filter(
            Q(nome_cliente__icontains=busca) | 
            Q(codigo_cliente__icontains=busca)
        )
    if vendedor_id:
        plantoes_list = plantoes_list.filter(vendedor_id=vendedor_id)
    if ocorrencia:
        plantoes_list = plantoes_list.filter(ocorrencia=ocorrencia)
    if data_f:
        plantoes_list = plantoes_list.filter(data_solicitacao__date=data_f)

    paginator = Paginator(plantoes_list, 10) 
    plantoes_obj = paginator.get_page(page_number)

    vVendedores = User.objects.filter(groups__name='Vendedores').distinct()

    context = {
        'plantoes': plantoes_obj,
        'vendedores': vVendedores,
        'pode_confirmar_plantao': no_grupo(request.user, *PLANTAO_EQUIPE),
    }

    return render(request, 'solicitacoes/plantao_list.html', context)

@grupo_requerido(*PLANTAO_ACESSO)
def excluir_plantao(request, pk):
    plantao = get_object_or_404(Plantao, pk=pk)
    if request.method != 'POST':
        return redirect('plantao_list')
    if not _pode_alterar_plantao(request.user, plantao):
        messages.error(request, "Você não tem permissão para excluir este plantão.")
    elif plantao.status == 'PENDENTE':
        plantao.delete()
        messages.success(request, "Solicitação excluída com sucesso.")
    else:
        messages.error(request, "Não é permitido excluir um plantão confirmado.")
    return redirect('plantao_list')

@grupo_requerido(*PLANTAO_ACESSO, json=True)
def get_plantao_detalhes(request, pk):
    plantao = get_object_or_404(Plantao, pk=pk)
    data = {
        'cliente': plantao.nome_cliente,
        'codigo': plantao.codigo_cliente,
        'loja': plantao.loja_cliente,
        'endereco': f"{plantao.endereco}, {plantao.numero} ({plantao.complemento or ''}) - {plantao.bairro}, {plantao.cidade}/{plantao.estado}",
        'tipo': plantao.tipo,
        'ocorrencia': plantao.ocorrencia,
        'vendedor': plantao.vendedor.get_full_name() if plantao.vendedor else "Não informado",
        'data_solicitacao': plantao.data_solicitacao.strftime('%d/%m/%Y'), # LINHA ADICIONADA
        'horario': plantao.horario.strftime('%H:%M') if plantao.horario else "--:--",
        'taxa': f"R$ {plantao.valor_taxa}" if plantao.taxa else "Isento",
        'obs': plantao.observacoes or "Nenhuma observação",
        'status': plantao.get_status_display()
    }
    return JsonResponse(data)

@login_required
def novo_plantao(request):
    if request.method == 'POST':
        horario_str = request.POST.get('horario')
        try:
            horario_obj = datetime.strptime(horario_str, '%H:%M').time() if horario_str else None
        except (ValueError, TypeError):
            horario_obj = None

        novo_plantao_obj = Plantao.objects.create(
            codigo_cliente=request.POST.get('codigo_cliente'),
            loja_cliente=request.POST.get('loja_cliente'),
            nome_cliente=request.POST.get('nome_cliente'),
            cep=request.POST.get('cep'),
            estado=request.POST.get('estado'),
            cidade=request.POST.get('cidade'),
            bairro=request.POST.get('bairro'),
            endereco=request.POST.get('endereco'),
            numero=request.POST.get('numero'),
            complemento=request.POST.get('complemento'),
            vendedor=request.user,
            tipo=request.POST.get('tipo'),
            ocorrencia=request.POST.get('ocorrencia'),
            ocorrencia_outro=request.POST.get('ocorrencia_outro'),
            observacoes=request.POST.get('observacoes'),
            taxa=(request.POST.get('taxa') == 'SIM'),
            valor_taxa=request.POST.get('valor_taxa', '0').replace('R$', '').replace('.', '').replace(',', '.').strip() or 0,
            horario=horario_obj
        )

        resultado_envio = disparar_plantao_whatsapp(novo_plantao_obj)

        if resultado_envio.get("sucesso"):
            messages.success(request, 'Solicitação gravada e mensagem enviada!')
        else:
            messages.warning(request, f"Gravado com sucesso, mas o WhatsApp não foi enviado.")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'sucesso'})

        return redirect('plantao_list')

    vendedores = User.objects.all()
    return render(request, 'solicitacoes/novo_plantao.html', {'vendedores': vendedores})
    
@grupo_requerido(*PLANTAO_ACESSO)
def editar_plantao(request, pk):

    plantao = get_object_or_404(Plantao, pk=pk)
    if not _pode_alterar_plantao(request.user, plantao):
        if request.method == 'POST':
            return JsonResponse({'status': 'erro', 'mensagem': 'Sem permissão.'}, status=403)
        messages.error(request, "Você não tem permissão para editar este plantão.")
        return redirect('plantao_list')
    
    if request.method == 'POST':
        plantao.codigo_cliente = request.POST.get('codigo_cliente')
        plantao.loja_cliente = request.POST.get('loja_cliente')
        plantao.nome_cliente = request.POST.get('nome_cliente')
        plantao.cep = request.POST.get('cep')
        plantao.estado = request.POST.get('estado')
        plantao.cidade = request.POST.get('cidade')
        plantao.bairro = request.POST.get('bairro')
        plantao.endereco = request.POST.get('endereco')
        plantao.numero = request.POST.get('numero')
        plantao.complemento = request.POST.get('complemento')
        plantao.tipo = request.POST.get('tipo')
        plantao.ocorrencia = request.POST.get('ocorrencia')
        plantao.taxa = (request.POST.get('taxa') == 'SIM')
        
        valor = request.POST.get('valor_taxa', '0,00')
        valor = valor.replace('R$', '').replace('.', '').replace(',', '.').strip()
        plantao.valor_taxa = float(valor) if valor else 0.0
        
        plantao.horario = request.POST.get('horario')
        plantao.observacoes = request.POST.get('observacoes')
        
        plantao.save()

        return JsonResponse({'status': 'sucesso'})

    return render(request, 'solicitacoes/novo_plantao.html', {
        'plantao': plantao, 
        'editando': True
    })

@login_required
def bonificacao_list(request):
    busca = request.GET.get('busca')
    tipo = request.GET.get('tipo')
    vendedor_id = request.GET.get('vendedor')
    status = request.GET.get('status')
    plataforma_filtro = request.GET.get('plataforma')
    data_param = request.GET.get('data_solicitacao')

    bonificacoes = Bonificacao.objects.select_related('vendedor').prefetch_related('itens').all().order_by('-data_solicitacao')

    eh_vendedor = eh_somente_vendedor(request.user)

    if eh_vendedor:
        bonificacoes = bonificacoes.filter(vendedor=request.user)
        usuarios_select = User.objects.filter(pk=request.user.pk)
    else:
        usuarios_select = User.objects.filter(groups__name='Vendedores', is_active=True).order_by('first_name')

    if plataforma_filtro:
        bonificacoes = bonificacoes.filter(plataforma=plataforma_filtro)

    if status:
        bonificacoes = bonificacoes.filter(status=status)

    if tipo:
        bonificacoes = bonificacoes.filter(tipo=tipo)

    if data_param:
        bonificacoes = bonificacoes.filter(data_solicitacao__date=data_param)

    if vendedor_id and not eh_vendedor:
        bonificacoes = bonificacoes.filter(vendedor_id=vendedor_id)

    if busca:
        if busca.isdigit():
            bonificacoes = bonificacoes.filter(
                Q(id=busca) | 
                Q(cliente_cpf_cnpj__icontains=busca) |
                Q(pedido_protheus__icontains=busca)
            )
        else:
            bonificacoes = bonificacoes.filter(
                Q(cliente_razao_social__icontains=busca) | 
                Q(cliente_nome_fantasia__icontains=busca)
            )

    paginator = Paginator(bonificacoes, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'bonificacoes': page_obj,
        'usuarios': usuarios_select,
        'status_choices': Bonificacao.STATUS_CHOICES if hasattr(Bonificacao, 'STATUS_CHOICES') else None,
    }
    
    return render(request, 'solicitacoes/bonificacao_list.html', context)

def enviar_emails_bonificacao(bonificacao, request):
    if bonificacao.tipo == 'ACORDO_COMERCIAL' and bonificacao.status == 'PENDENTE':
        destinatario = settings.EMAILS_BONIF_ACORDO_PENDENTE
        assunto = f"BONIFICAÇÃO PENDENTE (SEM ACORDO) - {bonificacao.cliente_razao_social}"
        template_name = 'solicitacoes/bonificacao_email_acordo.html'
    elif bonificacao.tipo == 'NEGOCIACAO_ESPECIAL' and bonificacao.status == 'PENDENTE':
        destinatario = settings.EMAILS_BONIF_NEGOCIACAO
        assunto = f"BONIFICAÇÃO PENDENTE DE APROVAÇÃO - {bonificacao.cliente_razao_social}"
        template_name = 'solicitacoes/bonificacao_email_aprovacao.html'
    elif bonificacao.tipo == 'SAC' and bonificacao.status == 'PENDENTE':
        destinatario = settings.EMAILS_BONIF_SAC
        assunto = f"BONIFICAÇÃO SAC PENDENTE - {bonificacao.cliente_razao_social}"
        template_name = 'solicitacoes/bonificacao_email_aprovacao.html'
    
    else:
        tem_chopp = bonificacao.itens.filter(produto_descricao__icontains='CHOPP').exists()
        template_name = 'solicitacoes/bonificacao_email.html'
        
        if tem_chopp:
            destinatario = settings.EMAILS_BONIF_CHOPP
            assunto = f"NOVO PEDIDO DE BONIFICAÇÃO - {bonificacao.cliente_razao_social}"
        else:
            destinatario = settings.EMAILS_BONIF_GERAL
            assunto = f"NOVO PEDIDO DE BONIFICAÇÃO - {bonificacao.cliente_razao_social}"

    total_geral = sum(item.valor_total for item in bonificacao.itens.all())

    contexto = {
        'bonificacao': bonificacao,
        'total_geral': f"{total_geral:,.2f}",
        'domain': request.get_host()
    }

    html_content = render_to_string(template_name, contexto)
    text_content = strip_tags(html_content)

    email = EmailMultiAlternatives(
        subject=assunto,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=list(destinatario)
    )
    email.attach_alternative(html_content, "text/html")
    email.send()

class SaldoAcordoInsuficiente(Exception):
    pass


def validar_saldo_acordo(acordo, itens_dados):
    """Levanta SaldoAcordoInsuficiente se a solicitação ultrapassar o saldo do acordo."""
    itens_do_acordo = [i for i in itens_dados if i.get('acordo_id') == acordo.id]

    if acordo.situacao != 'ATIVO':
        raise SaldoAcordoInsuficiente(
            f"O Acordo Comercial #{acordo.id} está encerrado e não aceita novas solicitações."
        )

    if acordo.tipo_acordo == 'produto':
        solicitado = {}
        for item in itens_do_acordo:
            cod = str(item['codigo']).strip()
            solicitado[cod] = solicitado.get(cod, 0) + item['qtd']

        saldos = acordo.saldos_por_produto()
        for cod, qtd in solicitado.items():
            saldo = saldos.get(cod, {}).get('saldo', 0)
            if qtd > saldo:
                raise SaldoAcordoInsuficiente(
                    f"Saldo insuficiente no Acordo #{acordo.id} para o produto {cod}: "
                    f"solicitado {qtd}, disponível {saldo}."
                )
    else:
        total = sum(Decimal(str(round(i['total'], 2))) for i in itens_do_acordo)
        saldo = acordo.saldo_disponivel
        if total > saldo:
            raise SaldoAcordoInsuficiente(
                f"Saldo insuficiente no Acordo #{acordo.id}: "
                f"solicitado R$ {total:.2f}, disponível R$ {saldo:.2f}."
            )


def recalcular_situacao_acordos(acordo_ids):
    """Reavalia ATIVO/ENCERRADO dos acordos após reprovar ou excluir uma bonificação."""
    for acordo in AcordoComercial.objects.filter(id__in=[i for i in acordo_ids if i]):
        acordo.atualizar_situacao()


@login_required
def criar_bonificacao(request):
    if request.method == 'POST':
        tipo = request.POST.get('tipo')
        hoje = timezone.now()
        hoje_date = hoje.date()
        
        cliente_razao = request.POST.get('cliente_razao_social')
        cliente_cnpj = request.POST.get('cliente_cpf_cnpj')
        cliente_cod = request.POST.get('cliente_codigo', '0')
        cliente_loja = request.POST.get('cliente_loja', '01')
        
        if not cliente_razao or not cliente_cnpj:
            messages.error(request, "Razão Social e CNPJ são obrigatórios.")
            return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

        itens_dados = []
        total_solicitacao = 0
        total_qtd_solicitacao = 0

        for key, value in request.POST.items():
            if key.startswith('item_nome_'):
                index = key.split('_')[-1]
                try:
                    preco_raw = request.POST.get(f'item_preco_{index}', '0').replace(',', '.')
                    qtd_raw = request.POST.get(f'item_qtd_{index}', '1')
                    
                    # CAPTURA O ACORDO SELECIONADO NA TELA PELO VENDEDOR:
                    acordo_id_raw = request.POST.get(f'item_acordo_{index}')
                    acordo_id = int(acordo_id_raw) if acordo_id_raw and acordo_id_raw.isdigit() else None
                    
                    preco = float(preco_raw) if preco_raw else 0.0
                    qtd = int(qtd_raw) if qtd_raw else 1
                    total_item = preco * qtd
                    
                    itens_dados.append({
                        'codigo': (request.POST.get(f'item_codigo_{index}') or 'TEMP').strip(),
                        'nome': value,
                        'preco': preco,
                        'qtd': qtd,
                        'total': total_item,
                        'acordo_id': acordo_id  # Guardamos o ID aqui
                    })
                    total_solicitacao += total_item
                    total_qtd_solicitacao += qtd
                except ValueError:
                    continue

        # Quantidade precisa ser positiva e todo item precisa ter código de produto
        for item in itens_dados:
            if item['qtd'] <= 0:
                messages.error(request, f"Quantidade inválida para o produto '{item['nome']}'.")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})
            if not item['codigo'] or item['codigo'] == 'TEMP':
                messages.error(request, f"Selecione o produto '{item['nome']}' pela busca do Protheus.")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

        # O preço é sempre o da tabela do Protheus (o que vier da tela é ignorado)
        try:
            precos = buscar_precos_protheus([i['codigo'] for i in itens_dados if i['codigo'] != CODIGO_COPO_BRINDE])
        except ProtheusIndisponivel as e:
            logger.error(f"Bonificação não gravada: {e}")
            messages.error(request, "Não foi possível consultar os preços no Protheus. Tente novamente em instantes.")
            return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})
        except Exception as e:
            logger.exception("Erro ao consultar preços no Protheus")
            messages.error(request, "Não foi possível consultar os preços no Protheus. Tente novamente em instantes.")
            return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

        total_solicitacao = 0
        for item in itens_dados:
            if item['codigo'] == CODIGO_COPO_BRINDE:
                item['preco'] = 0.0
            elif item['codigo'] in precos:
                item['preco'] = float(precos[item['codigo']])
            else:
                messages.error(request, f"Preço do produto '{item['nome']}' (Cód: {item['codigo']}) não encontrado na tabela do Protheus.")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})
            item['total'] = round(item['preco'] * item['qtd'], 2)
            total_solicitacao += item['total']

        status_final = 'PENDENTE'
        acordo = None
        
        if tipo == 'SAC':
            status_final = 'PENDENTE'

        elif tipo == 'NEGOCIACAO_ESPECIAL':
            status_final = 'PENDENTE'

        elif tipo == 'ACORDO_COMERCIAL':
            # 1. Captura o ID do acordo selecionado globalmente no formulário
            acordo_id_global = request.POST.get('acordo_id_global')
            
            if not acordo_id_global:
                messages.error(
                    request, 
                    "Não é possível gravar a solicitação: nenhum Acordo Comercial foi selecionado."
                )
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})
            
            try:
                # Busca o acordo no banco de dados do app cadastros
                from cadastros.models import AcordoComercial
                acordo = AcordoComercial.objects.get(id=acordo_id_global)
            except AcordoComercial.DoesNotExist:
                messages.error(request, "O Acordo Comercial selecionado não foi encontrado no sistema.")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

            if acordo.situacao != 'ATIVO':
                messages.error(
                    request,
                    f"O Acordo Comercial #{acordo.id} está encerrado e não aceita novas solicitações."
                )
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

            # 2. Validação se o acordo for por PRODUTO
            if acordo.tipo_acordo == 'produto':
                # Mapeia todos os códigos de produtos permitidos neste acordo específico
                produtos_permitidos = set(acordo.itens.values_list('produto_codigo', flat=True))
                
                # Verifica se há algum item na lista da bonificação que NÃO está no acordo
                for item in itens_dados:
                    cod_produto = item.get('codigo')  # Ajustado para buscar a chave correta 'codigo'
                    nome_produto = item.get('nome')
                    
                    # EXCEÇÃO: Se for o Copo Brinde da fábrica, ignora a validação do Acordo Comercial
                    if cod_produto == CODIGO_COPO_BRINDE:
                        continue
                    
                    if cod_produto not in produtos_permitidos:
                        messages.error(
                            request, 
                            f"Gravação Recusada: O produto '{nome_produto}' (Cód: {cod_produto}) não faz parte das regras deste Acordo Comercial."
                        )
                        return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

            # 3. Se passou pelas validações, vincula o acordo aos itens (com exceção do copo brinde)
            for item in itens_dados:
                if item.get('codigo') == CODIGO_COPO_BRINDE:
                    item['acordo_id'] = None  # O copo não consome saldo de contrato
                else:
                    item['acordo_id'] = acordo.id

            status_final = 'APROVADO'

        elif tipo == 'VERBA_VENDEDOR':
            verba_configurada = VerbaMensal.objects.filter(
                vendedor=request.user, 
                mes_referencia=hoje.month, 
                ano_referencia=hoje.year
            ).first()

            if not verba_configurada:
                messages.error(request, f"Não existe verba cadastrada para o período {hoje.month}/{hoje.year}.")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

            
            saldo_disponivel = float(verba_configurada.valor) - float(verba_configurada.valor_utilizado)
            
            if total_solicitacao > saldo_disponivel:
                messages.error(request, f"Saldo Insuficiente para o mês {hoje.month}/{hoje.year}! Disponível: R$ {saldo_disponivel:,.2f}")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})
            
            status_final = 'APROVADO'

        acordo_encerrado = False

        try:
            with transaction.atomic():
                if acordo:
                    # Trava o acordo para duas solicitações simultâneas não consumirem o mesmo saldo
                    acordo = AcordoComercial.objects.select_for_update().get(pk=acordo.pk)
                    validar_saldo_acordo(acordo, itens_dados)

                if tipo == 'VERBA_VENDEDOR':
                    # Mesma trava para a verba mensal: confere de novo o saldo com a verba bloqueada
                    verba_travada = VerbaMensal.objects.select_for_update().get(pk=verba_configurada.pk)
                    saldo_atual = float(verba_travada.valor) - float(verba_travada.valor_utilizado)
                    if total_solicitacao > saldo_atual:
                        raise SaldoAcordoInsuficiente(
                            f"Saldo Insuficiente para o mês {hoje.month}/{hoje.year}! Disponível: R$ {saldo_atual:,.2f}"
                        )

                nova_bonif = Bonificacao.objects.create(
                    tipo=tipo,
                    vendedor=request.user,
                    cliente_razao_social=cliente_razao,
                    cliente_nome_fantasia=request.POST.get('cliente_nome_fantasia', ''),
                    cliente_codigo=cliente_cod,
                    cliente_loja=cliente_loja,
                    cliente_cpf_cnpj=cliente_cnpj,
                    cliente_grupo=request.POST.get('cliente_grupo', ''),
                    justificativa=request.POST.get('justificativa', ''),
                    status=status_final,
                    plataforma=request.POST.get('plataforma'),
                    metodo_entrega=request.POST.get('metodo_entrega'),
                    data_entrega_retirada=request.POST.get('data_entrega_retirada') or None,
                    foto_sac=request.FILES.get('foto_sac')
                )

                for f in request.FILES.getlist('foto_sac'):
                    FotoBonificacao.objects.create(
                        bonificacao=nova_bonif,
                        arquivo=f
                    )

                for item in itens_dados:
                    BonificacaoItem.objects.create(
                        bonificacao=nova_bonif,
                        produto_codigo=item['codigo'],
                        produto_descricao=item['nome'],
                        preco_tabela=item['preco'],
                        quantidade=item['qtd'],
                        valor_total=item['total'],
                        acordo_vinculado_id=item['acordo_id']  # Grava a FK do acordo escolhido (ou None pro copo)
                    )

                # Saldo zerou com esta solicitação -> encerra o acordo automaticamente
                if acordo:
                    acordo_encerrado = acordo.atualizar_situacao() == 'ENCERRADO'

            if acordo_encerrado:
                messages.info(
                    request,
                    f"O saldo do Acordo Comercial #{acordo.id} foi totalmente utilizado e o acordo foi encerrado."
                )

            try:
                enviar_emails_bonificacao(nova_bonif, request)
                if status_final == 'PENDENTE':
                    messages.info(request, "Solicitação enviada para aprovação.")
            except Exception:
                messages.warning(request, "Gravado, mas houve erro no envio do e-mail.")

            return redirect('bonificacao_list')

        except SaldoAcordoInsuficiente as e:
            messages.error(request, str(e))
            return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

        except Exception as e:
            messages.error(request, f"Erro técnico ao salvar: {str(e)}")
            return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

    return render(request, 'solicitacoes/bonificacao_form.html')

@login_required
def gerenciar_solicitacao(request, pk, acao):
    solicitacao = get_object_or_404(Bonificacao, pk=pk)

    # Só por formulário (POST): um link aberto por engano não pode aprovar nada
    if request.method != 'POST':
        messages.error(request, "Ação inválida.")
        return redirect('bonificacao_list')

    if acao in ('aprovar', 'reprovar') and not (
        no_grupo(request.user, *GESTAO_COMERCIAL) and solicitacao.status == 'PENDENTE'
    ):
        messages.error(request, "Você não tem permissão para aprovar ou reprovar esta solicitação.")
        return redirect('bonificacao_list')

    if acao == 'concluir' and not (
        no_grupo(request.user, *FATURAMENTO) and solicitacao.status == 'APROVADO'
    ):
        messages.error(request, "Você não tem permissão para concluir esta solicitação.")
        return redirect('bonificacao_list')

    if acao == 'aprovar':
        solicitacao.status = 'APROVADO'
        solicitacao.data_aprovacao = timezone.now()
        solicitacao.usuario_aprovador = request.user
        solicitacao.save()

        try:
            enviar_emails_bonificacao(solicitacao, request)
            messages.success(request, f"Solicitação {acao} com sucesso e e-mails enviados.")
        except Exception as e:
            logger.error(f"Erro ao enviar e-mail de aprovação da bonificação #{solicitacao.id}: {e}")
            messages.warning(request, f"Solicitação {acao}, mas não foi possível enviar o e-mail de notificação (Erro de SMTP).")

    elif acao == 'reprovar':
        motivo = request.POST.get('motivo')
        if motivo:
            solicitacao.status = 'REPROVADO'
            solicitacao.observacao_reprovacao = motivo
            solicitacao.usuario_aprovador = request.user
            solicitacao.data_aprovacao = timezone.now()
            solicitacao.save()
            # A reprovação devolve o saldo: reabre o acordo se ele tinha sido encerrado
            recalcular_situacao_acordos(
                solicitacao.itens.values_list('acordo_vinculado_id', flat=True).distinct()
            )
            messages.success(request, f"Solicitação {pk} reprovada.")
        else:
            messages.error(request, "É necessário informar o motivo da reprovação.")
    
    elif acao == 'concluir':
        numero_pedido = request.POST.get('pedido_erp')
        if numero_pedido:
            solicitacao.pedido_protheus = numero_pedido
            solicitacao.status = 'CONCLUIDO'
            solicitacao.save()
            messages.success(request, f"Pedido {numero_pedido} confirmado com sucesso!")
        else:
            messages.error(request, "Número do pedido não informado.")
            
    return redirect('bonificacao_list')

@grupo_requerido(*PLANTAO_EQUIPE, destino='plantao_list')
def confirmar_plantao(request, pk):
    if request.method == 'POST':
        plantao = get_object_or_404(Plantao, pk=pk)
    
        plantao.status = 'CONFIRMADO' 
        
        plantao.save()
        
        messages.success(request, f"Plantão de {plantao.nome_cliente} confirmado com sucesso!")
        
    return redirect('plantao_list')

@login_required
def excluir_bonificacao(request, pk):
    bonificacao = get_object_or_404(Bonificacao, pk=pk)
    if request.method == 'POST' and no_grupo(request.user, *GESTAO_COMERCIAL) and bonificacao.status != 'CONCLUIDO':
        acordo_ids = list(bonificacao.itens.values_list('acordo_vinculado_id', flat=True).distinct())
        bonificacao.delete()
        # A exclusão devolve o saldo: reabre o acordo se ele tinha sido encerrado
        recalcular_situacao_acordos(acordo_ids)
        messages.success(request, "Solicitação excluída com sucesso.")
    else:
        messages.error(request, "Não é permitido excluir esta solicitação.")
    return redirect('bonificacao_list')

_FONTE_PDF_OK = None


def _registrar_fonte_pdf():
    """
    Registra a IBM Plex Sans direto no ReportLab, a partir de static/fonts.
    (Registrar pelo @font-face do HTML falha no Windows por causa de arquivo temporário.)
    Se os arquivos não existirem, o PDF continua saindo em Helvetica.
    """
    global _FONTE_PDF_OK
    if _FONTE_PDF_OK is not None:
        return _FONTE_PDF_OK
    try:
        from django.contrib.staticfiles import finders
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.fonts import addMapping
        from xhtml2pdf import default as pisa_default

        normal = finders.find('fonts/IBMPlexSans-Regular.ttf')
        negrito = finders.find('fonts/IBMPlexSans-SemiBold.ttf')
        if not (normal and negrito):
            _FONTE_PDF_OK = False
            return False

        pdfmetrics.registerFont(TTFont('IBMPlexSans', normal))
        pdfmetrics.registerFont(TTFont('IBMPlexSans-Bold', negrito))
        for italico in (0, 1):
            addMapping('IBMPlexSans', 0, italico, 'IBMPlexSans')
            addMapping('IBMPlexSans', 1, italico, 'IBMPlexSans-Bold')
        for chave in ('ibm plex sans', 'ibmplexsans'):
            pisa_default.DEFAULT_FONT[chave] = 'IBMPlexSans'
        pisa_default.DEFAULT_FONT['ibmplexsans-bold'] = 'IBMPlexSans-Bold'
        _FONTE_PDF_OK = True
    except Exception as e:
        logger.warning("Fonte do PDF não registrada, usando Helvetica: %s", e)
        _FONTE_PDF_OK = False
    return _FONTE_PDF_OK


@login_required
def gerar_pdf_bonificacao(request, pk):
    bonificacao = get_object_or_404(Bonificacao, pk=pk)
    if not pode_ver_bonificacao(request.user, bonificacao):
        raise Http404("Bonificação não encontrada.")
    
    context = {
        'b': bonificacao,
        'data': timezone.now(),
    }
    
    _registrar_fonte_pdf()
    html = render_to_string('solicitacoes/bonificacao_pdf.html', context)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="bonificacao_{pk}.pdf"'
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return HttpResponse('Erro ao gerar PDF', status=500)
    
    return response

@grupo_requerido(*GESTAO_COMERCIAL, destino='bonificacao_list')
def exportar_bonificacoes_excel(request):
    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')

    queryset = Bonificacao.objects.select_related('vendedor').prefetch_related('itens')
    
    if data_inicio:
        queryset = queryset.filter(data_solicitacao__date__gte=data_inicio)
    if data_fim:
        queryset = queryset.filter(data_solicitacao__date__lte=data_fim)

    dados = []
    for b in queryset:
        dados.append({
            'ID': b.id,
            'Data Solicitação': b.data_solicitacao.replace(tzinfo=None),
            'Vendedor': b.vendedor.get_full_name() if b.vendedor else 'N/A',
            'Cliente (Razão Social)': b.cliente_razao_social,
            'CPF/CNPJ': b.cliente_cpf_cnpj,
            'Tipo': b.get_tipo_display(),
            'Plataforma': b.plataforma,
            'Status': b.get_status_display(),
            'Valor Total': b.get_total(),
            'Pedido ERP': b.pedido_protheus or '',
            'Justificativa': b.justificativa or ''
        })

    df = pd.DataFrame(dados)

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename=bonificacoes_{data_inicio}_a_{data_fim}.xlsx'

    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Bonificações')

    return response