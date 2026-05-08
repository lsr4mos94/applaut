import os
import base64
import logging
from datetime import date, datetime, timedelta
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
from .models import Plantao, Bonificacao, BonificacaoItem
from .services import buscar_cliente_protheus_unificado
from cadastros.models import VerbaMensal, AcordoComercial

logger = logging.getLogger(__name__)

def disparar_plantao_whatsapp(solicitacao):
    url = "https://api.zenvia.com/v2/channels/whatsapp/messages"
    headers = {
        "X-API-TOKEN": "Kn3XB8ntqaeCASe7_wFT-vqHW-IvdwMsbwLR",
        "Content-Type": "application/json"
    }
    
    endereco_completo = f"{solicitacao.endereco}, {solicitacao.numero}, {solicitacao.bairro} - {solicitacao.cidade}"

    payload = {
        "from": "553190004411",
        "to": "5531971560752",
        "contents": [
            {
                "type": "template",
                "templateId": "358e7517-8beb-4161-af5f-8086fe7c6c91",
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
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        
        print(f"DEBUG ZENVIA: {response_data}") 

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
    
    vendedor_cod = request.user.perfil.codigo_vendedor
    
    if vendedor_cod:
        resultados = buscar_cliente_protheus_unificado(termo, vendedor_cod)
    else:
        resultados = []
        
    return JsonResponse(resultados, safe=False)

def buscar_produto_protheus_unificado(request):
    termo = request.GET.get('q', '').upper().strip()
    if not termo or len(termo) < 3:
        return JsonResponse([], safe=False)

    config_busca = {
        'protheus_ciec': ['SB1010', 'SB1020'],
        'protheus_wrp': ['SB1010']
    }

    query_template = """
        SELECT 
            SB1.B1_COD, 
            SB1.B1_DESC, 
            ISNULL(SBM.BM_DESC, 'SEM GRUPO') as BM_DESC, 
            DA1.DA1_PRCVEN
        FROM {tabela} AS SB1
        LEFT JOIN SBM{empresa} AS SBM ON 
            RTRIM(SBM.BM_GRUPO) = RTRIM(SB1.B1_GRUPO) AND SBM.D_E_L_E_T_ <> '*'
        INNER JOIN DA1{empresa} AS DA1 ON 
            DA1.DA1_CODTAB = '214' 
            AND RTRIM(DA1.DA1_CODPRO) = RTRIM(SB1.B1_COD) 
            AND DA1.D_E_L_E_T_ <> '*'
        WHERE SB1.D_E_L_E_T_ <> '*' 
        AND SB1.B1_MSBLQL <> '1' 
        AND (SB1.B1_DESC LIKE %s OR SB1.B1_COD LIKE %s)
    """
    
    produtos_dict = {}
    params = [f'%{termo}%', f'%{termo}%']

    for db, tabelas in config_busca.items():
        if db not in connections: continue
        
        for tabela in tabelas:
            empresa_sufixo = tabela[-3:] 
            
            try:
                with connections[db].cursor() as cursor:
                    cursor.execute(query_template.format(tabela=tabela, empresa=empresa_sufixo), params)
                    
                    for row in cursor.fetchall():
                        cod_limpo = row[0].strip()

                        if cod_limpo not in produtos_dict:
                            produtos_dict[cod_limpo] = {
                                'codigo': cod_limpo,
                                'descricao': row[1].strip(),
                                'grupo_familia': row[2].strip(),
                                'preco': float(row[3]) if row[3] is not None else 0.0
                            }
            except Exception as e:
                continue

    return JsonResponse(list(produtos_dict.values()), safe=False)

@login_required
def buscar_boleto(request):
    lista_boletos = []
    numero_nota = request.POST.get('numero_nota', '').strip()
    abrir_modal = False

    if request.method == 'POST' and numero_nota:
        caminho_base = r'\\SRV-FILESERVER\Faturamento\DOCUMENTOS FISCAIS\2026'
        
        if not os.path.exists(caminho_base):
            logger.error(f"ERRO DE ACESSO: O caminho {caminho_base} não foi encontrado.")
            return render(request, 'solicitacoes/boletos.html', {
                'mensagem': 'O servidor de arquivos (2026) está inacessível.',
                'tipo_mensagem': 'erro',
                'numero_nota': numero_nota
            })

        data_limite = (datetime.now() - timedelta(days=90)).timestamp()

        try:
            for raiz, _, arquivos in os.walk(caminho_base):
                for nome_arquivo in arquivos:
                    nome_comparar = nome_arquivo.upper()
                    termo_comparar = numero_nota.upper()

                    if termo_comparar in nome_comparar and nome_comparar.endswith('.PDF'):
                        caminho_completo = os.path.join(raiz, nome_arquivo)

                        try:
                            data_modificacao = os.path.getmtime(caminho_completo)
                            
                            if data_modificacao >= data_limite:
                                caminho_encoded = base64.urlsafe_b64encode(caminho_completo.encode()).decode()
                                
                                lista_boletos.append({
                                    'nome': nome_arquivo,
                                    'caminho': caminho_encoded,
                                    'data': data_modificacao
                                })
                        except Exception as e:
                            continue
            
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
        
        if os.path.exists(caminho_real):
            with open(caminho_real, 'rb') as f:
                response = HttpResponse(f.read(), content_type='application/pdf')
                response['Content-Disposition'] = f'inline; filename="{os.path.basename(caminho_real)}"'
                return response
        else:
            raise Http404("Arquivo não encontrado no servidor.")
    except Exception as e:
        logger.error(f"Erro no download do boleto: {e}")
        raise Http404("Erro ao processar o arquivo.")

def plantao_list(request):
    if request.method == 'POST' and 'plantao_id' in request.POST:
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
    }

    return render(request, 'solicitacoes/plantao_list.html', context)

def excluir_plantao(request, pk):
    plantao = get_object_or_404(Plantao, pk=pk)
    if plantao.status == 'PENDENTE':
        plantao.delete()
        messages.success(request, "Solicitação excluída com sucesso.")
    else:
        messages.error(request, "Não é permitido excluir um plantão confirmado.")
    return redirect('plantao_list')

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
    
def editar_plantao(request, pk):

    plantao = get_object_or_404(Plantao, pk=pk)
    
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

    eh_vendedor = request.user.groups.filter(name='Vendedores').exists()

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
        destinatario = 'admcomercial@lautbeer.com.br'
        assunto = f"BONIFICAÇÃO PENDENTE (SEM ACORDO) - {bonificacao.cliente_razao_social}"
        template_name = 'solicitacoes/bonificacao_email_acordo.html'
    elif bonificacao.tipo == 'NEGOCIACAO_ESPECIAL' and bonificacao.status == 'PENDENTE':
        destinatario = 'wellington@lautbeer.com.br'
        assunto = f"BONIFICAÇÃO PENDENTE DE APROVAÇÃO - {bonificacao.cliente_razao_social}"
        template_name = 'solicitacoes/bonificacao_email_aprovacao.html'
    elif bonificacao.tipo == 'SAC' and bonificacao.status == 'PENDENTE':
        destinatario = 'admcomercial@lautbeer.com.br'
        assunto = f"BONIFICAÇÃO SAC PENDENTE - {bonificacao.cliente_razao_social}"
        template_name = 'solicitacoes/bonificacao_email_aprovacao.html'
    
    else:
        tem_chopp = bonificacao.itens.filter(produto_descricao__icontains='CHOPP').exists()
        template_name = 'solicitacoes/bonificacao_email.html'
        
        if tem_chopp:
            destinatario = 'adm1@lautbeer.com.br'
            assunto = f"NOVO PEDIDO DE BONIFICAÇÃO - {bonificacao.cliente_razao_social}"
        else:
            destinatario = 'admcomercial@lautbeer.com.br'
            assunto = f"NOVO PEDIDO DE BONIFICAÇÃO- {bonificacao.cliente_razao_social}"

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
        from_email="workflow@lautbeer.cpm.br",
        to=[destinatario]
    )
    email.attach_alternative(html_content, "text/html")
    email.send()

def validar_limite_por_cliente(vendedor, cliente_cnpj, valor_nova_solicitacao):
    try:
        verba = VerbaMensal.objects.get(vendedor=vendedor)
    except VerbaMensal.DoesNotExist:
        return

    limite_valor = verba.limite_por_cliente

    mes_atual = date.today().month
    ano_atual = date.today().year
    
    total_ja_concedido = Bonificacao.objects.filter(
        vendedor=vendedor,
        cliente_cpf_cnpj=cliente_cnpj,
        data_solicitacao__month=mes_atual,
        data_solicitacao__year=ano_atual,
        status__in=['APROVADO', 'PENDENTE']
    ).aggregate(total=Sum('itens__valor_total'))['total'] or 0

    if (total_ja_concedido + valor_nova_solicitacao) > limite_valor:
        percentual = verba.percentual_limite_por_cliente
        raise ValidationError(
            f"Limite por cliente excedido! Este cliente já possui R$ {total_ja_concedido:.2f} em bonificações este mês. "
            f"O limite máximo permitido é de {percentual}% da sua verba (R$ {limite_valor:.2f})."
        )

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
                    
                    preco = float(preco_raw) if preco_raw else 0.0
                    qtd = int(qtd_raw) if qtd_raw else 1
                    total_item = preco * qtd
                    
                    itens_dados.append({
                        'codigo': request.POST.get(f'item_codigo_{index}', 'TEMP'),
                        'nome': value,
                        'preco': preco,
                        'qtd': qtd,
                        'total': total_item
                    })
                    total_solicitacao += total_item
                    total_qtd_solicitacao += qtd
                except ValueError:
                    continue

        status_final = 'PENDENTE'
        
        if tipo == 'SAC':
            status_final = 'PENDENTE'

        elif tipo == 'NEGOCIACAO_ESPECIAL':
            status_final = 'PENDENTE'

        elif tipo == 'ACORDO_COMERCIAL':
            acordo = AcordoComercial.objects.filter(
                cliente_codigo=cliente_cod,
                cliente_loja=cliente_loja,
                vigencia_inicio__lte=hoje_date,
                vigencia_fim__gte=hoje_date
            ).first()

            if not acordo:
                status_final = 'PENDENTE'
                messages.warning(request, "Nenhum acordo vigente encontrado. A solicitação seguirá para aprovação manual.")
            else:
                realizado_protheus = calcular_realizado_protheus(cliente_cod, cliente_loja, acordo.vigencia_inicio, acordo.vigencia_fim)
                
                # --- CORREÇÃO: FILTRAR ITENS DO ACORDO ---
                codigos_no_acordo = list(acordo.itens.values_list('produto_codigo', flat=True))
                
                if acordo.tipo_acordo == 'valor':
                    reservado_local = BonificacaoItem.objects.filter(
                        bonificacao__cliente_codigo=cliente_cod,
                        bonificacao__tipo='ACORDO_COMERCIAL',
                        bonificacao__status__in=['APROVADO'],
                        bonificacao__data_solicitacao__range=(acordo.vigencia_inicio, acordo.vigencia_fim)
                    ).aggregate(total=Sum('valor_total'))['total'] or 0

                    objetivo = float(acordo.valor_acordo)
                    consumido = float(realizado_protheus['valor']) + float(reservado_local)
                    disponivel = objetivo - consumido
                    solicitado = total_solicitacao
                    unidade = "R$"
                else:
                    # Se for quantidade, filtramos o que já foi gasto localmente apenas dos produtos do acordo
                    reservado_local = BonificacaoItem.objects.filter(
                        bonificacao__cliente_codigo=cliente_cod,
                        bonificacao__tipo='ACORDO_COMERCIAL',
                        bonificacao__status__in=['APROVADO'],
                        bonificacao__data_solicitacao__range=(acordo.vigencia_inicio, acordo.vigencia_fim),
                        produto_codigo__in=codigos_no_acordo
                    ).aggregate(total=Sum('quantidade'))['total'] or 0

                    # Somamos da solicitação atual APENAS o que for produto do acordo
                    solicitado_filtrado = sum(item['qtd'] for item in itens_dados if item['codigo'] in codigos_no_acordo)

                    objetivo = sum(item.qtd_faturada for item in acordo.itens.all())
                    consumido = realizado_protheus['qtd'] + reservado_local
                    disponivel = objetivo - consumido
                    solicitado = solicitado_filtrado
                    unidade = "UN"

                if solicitado <= disponivel:
                    status_final = 'APROVADO'
                    messages.success(request, f"Bonificação aprovada automaticamente! Saldo restante: {unidade} {disponivel - solicitado:,.2f}")
                else:
                    messages.error(request, f"Saldo insuficiente no acordo! Disponível: {unidade} {disponivel:,.2f}. Solicitado (itens do acordo): {unidade} {solicitado:,.2f}")
                    return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

        elif tipo == 'VERBA_VENDEDOR':
            verba_configurada = VerbaMensal.objects.filter(
                vendedor=request.user, 
                mes_referencia=hoje.month, 
                ano_referencia=hoje.year
            ).first()

            if not verba_configurada:
                messages.error(request, f"Não existe verba cadastrada para o período {hoje.month}/{hoje.year}.")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

            limite_valor_cliente = float(verba_configurada.limite_por_cliente)
            
            ja_gasto_cliente = Bonificacao.objects.filter(
                vendedor=request.user, 
                cliente_cpf_cnpj=cliente_cnpj,
                data_solicitacao__month=hoje.month, 
                data_solicitacao__year=hoje.year,
                status__in=['APROVADO', 'PENDENTE', 'CONCLUIDO']
            ).aggregate(total=Sum('itens__valor_total'))['total'] or 0

            if (float(ja_gasto_cliente) + total_solicitacao) > limite_valor_cliente:
                messages.error(request, f"Limite por cliente excedido! O máximo para este cliente é R$ {limite_valor_cliente:,.2f}")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

            gastos_totais_mes = Bonificacao.objects.filter(
                vendedor=request.user, 
                tipo='VERBA_VENDEDOR',
                data_solicitacao__month=hoje.month,
                data_solicitacao__year=hoje.year,
                status__in=['APROVADO', 'PENDENTE', 'CONCLUIDO']
            ).aggregate(total=Sum('itens__valor_total'))['total'] or 0

            saldo_disponivel = float(verba_configurada.valor) - float(gastos_totais_mes)
            
            if total_solicitacao > saldo_disponivel:
                messages.error(request, f"Saldo Insuficiente para o mês {hoje.month}/{hoje.year}! Disponível: R$ {saldo_disponivel:,.2f}")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})
            
            status_final = 'APROVADO'

        try:
            with transaction.atomic():
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

                for item in itens_dados:
                    BonificacaoItem.objects.create(
                        bonificacao=nova_bonif,
                        produto_codigo=item['codigo'],
                        produto_descricao=item['nome'],
                        preco_tabela=item['preco'],
                        quantidade=item['qtd'],
                        valor_total=item['total']
                    )

            try:
                enviar_emails_bonificacao(nova_bonif, request)
                if status_final == 'PENDENTE':
                    messages.info(request, "Solicitação enviada para aprovação.")
            except Exception:
                messages.warning(request, "Gravado, mas houve erro no envio do e-mail.")

            return redirect('bonificacao_list')

        except Exception as e:
            messages.error(request, f"Erro técnico ao salvar: {str(e)}")
            return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

    return render(request, 'solicitacoes/bonificacao_form.html')

def calcular_realizado_protheus(cliente, loja, inicio, fim):
    bases = {'protheus_ciec': ['SD2010', 'SD2020'], 'protheus_wrp': ['SD2010']}
    total_valor = 0.0
    total_qtd = 0.0
    d1, d2 = inicio.strftime('%Y%m%d'), fim.strftime('%Y%m%d')

    for db, tabelas in bases.items():
        for tab in tabelas:
            emp = tab[-3:]
            query = f"SELECT SUM(D2_TOTAL), SUM(D2_QUANT) FROM {tab} AS SD2 INNER JOIN SF4{emp} AS SF4 ON SF4.F4_FILIAL = SD2.D2_FILIAL AND SF4.F4_CODIGO = SD2.D2_TES AND SF4.D_E_L_E_T_ <> '*' INNER JOIN SC5{emp} AS SC5 ON SC5.C5_FILIAL = SD2.D2_FILIAL AND SC5.C5_NUM = SD2.D2_PEDIDO AND SC5.D_E_L_E_T_ <> '*' WHERE SD2.D_E_L_E_T_ <> '*' AND D2_CLIENTE = %s AND D2_LOJA = %s AND  D2_EMISSAO BETWEEN %s AND %s AND SF4.F4_BONIF = 'S' AND SC5.C5_ZTPBONI = '1'"
            with connections[db].cursor() as cursor:
                cursor.execute(query, [cliente, loja, d1, d2])
                res = cursor.fetchone()
                total_valor += float(res[0] or 0)
                total_qtd += float(res[1] or 0)
    return {'valor': total_valor, 'qtd': total_qtd}

@login_required
def gerenciar_solicitacao(request, pk, acao):
    solicitacao = get_object_or_404(Bonificacao, pk=pk)

    if acao == 'aprovar':
        solicitacao.status = 'APROVADO'
        solicitacao.data_aprovacao = timezone.now()
        solicitacao.usuario_aprovador = request.user
        solicitacao.save()

        try:
            enviar_emails_bonificacao(request, solicitacao)
            messages.success(request, f"Solicitação {acao} com sucesso e e-mails enviados.")
        except Exception as e:
            print(f"Erro ao enviar e-mail: {e}") 
            messages.warning(request, f"Solicitação {acao}, mas não foi possível enviar o e-mail de notificação (Erro de SMTP).")

    elif acao == 'reprovar' and request.method == 'POST':
        motivo = request.POST.get('motivo')
        if motivo:
            solicitacao.status = 'REPROVADO'
            solicitacao.observacao_reprovacao = motivo
            solicitacao.usuario_aprovador = request.user
            solicitacao.data_aprovacao = timezone.now()
            solicitacao.save()
            messages.success(request, f"Solicitação {pk} reprovada.")
        else:
            messages.error(request, "É necessário informar o motivo da reprovação.")
    
    elif acao == 'concluir' and request.method == 'POST':
        numero_pedido = request.POST.get('pedido_erp')
        if numero_pedido:
            solicitacao.pedido_protheus = numero_pedido
            solicitacao.status = 'CONCLUIDO'
            solicitacao.save()
            messages.success(request, f"Pedido {numero_pedido} confirmado com sucesso!")
        else:
            messages.error(request, "Número do pedido não informado.")
            
    return redirect('bonificacao_list')

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
    if not request.user.groups.filter(name='Vendedores').exists() and bonificacao.status != 'CONCLUIDO':
        bonificacao.delete()
        messages.success(request, "Solicitação excluída com sucesso.")
    else:
        messages.error(request, "Não é permitido excluir esta solicitação.")
    return redirect('bonificacao_list')

@login_required
def gerar_pdf_bonificacao(request, pk):
    bonificacao = get_object_or_404(Bonificacao, pk=pk)
    
    context = {
        'b': bonificacao,
        'data': timezone.now(),
    }
    
    html = render_to_string('solicitacoes/bonificacao_pdf.html', context)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="bonificacao_{pk}.pdf"'
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    
    if pisa_status.err:
        return HttpResponse('Erro ao gerar PDF', status=500)
    
    return response

def exportar_bonificacoes_excel(request):
    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')

    queryset = Bonificacao.objects.all()
    
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