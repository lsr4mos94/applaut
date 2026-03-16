import os
import base64
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404, JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from .models import Plantao
from django.db.models import Sum
from django.utils import timezone
from .models import Bonificacao, BonificacaoItem
from cadastros.models import VerbaMensal, AcordoComercial
from usuarios.models import Perfil
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum
from datetime import date
from .services import buscar_cliente_protheus_unificado
from django.db.models import Q
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction, connections
from xhtml2pdf import pisa

logger = logging.getLogger(__name__)

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

import os
import base64
import logging
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

# Configuração básica de log para ver erros no terminal do VS Code/PyCharm
logger = logging.getLogger(__name__)

@login_required
def buscar_boleto(request):
    lista_boletos = []
    numero_nota = request.POST.get('numero_nota', '').strip()
    abrir_modal = False

    if request.method == 'POST' and numero_nota:
        # Usando r'' para strings brutas (raw) e garantindo as barras invertidas do Windows
        caminho_base = r'\\SRV-FILESERVER\Faturamento\DOCUMENTOS FISCAIS\2026'
        
        # 1. Validação de Acesso ao Servidor
        if not os.path.exists(caminho_base):
            logger.error(f"ERRO DE ACESSO: O caminho {caminho_base} não foi encontrado ou está inacessível.")
            return render(request, 'solicitacoes/boletos.html', {
                'mensagem': 'O servidor de arquivos (2026) está inacessível. Verifique a rede ou permissões.',
                'tipo_mensagem': 'erro',
                'numero_nota': numero_nota
            })

        try:
            # 2. Busca Recursiva
            for raiz, _, arquivos in os.walk(caminho_base):
                for nome_arquivo in arquivos:
                    nome_comparar = nome_arquivo.upper()
                    termo_comparar = numero_nota.upper()

                    # Verifica se o número está no nome e se é um PDF (independente de ser .pdf ou .PDF)
                    if termo_comparar in nome_comparar and nome_comparar.endswith('.PDF'):
                        caminho_completo = os.path.join(raiz, nome_arquivo)

                        try:
                            # Encode do caminho para usar na URL de download/visualização
                            caminho_encoded = base64.urlsafe_b64encode(caminho_completo.encode()).decode()
                            
                            lista_boletos.append({
                                'nome': nome_arquivo,
                                'caminho': caminho_encoded,
                                'data': os.path.getmtime(caminho_completo)
                            })
                        except Exception as e:
                            logger.warning(f"Não foi possível ler metadados do arquivo {nome_arquivo}: {e}")
                            continue
            
            # Ordenar por data de modificação (mais recentes primeiro)
            lista_boletos.sort(key=lambda x: x['data'], reverse=True)
            abrir_modal = True if lista_boletos else False

        except Exception as e:
            logger.exception("Erro grave durante a busca de arquivos:")
            return render(request, 'solicitacoes/boletos.html', {
                'mensagem': f'Erro interno ao processar arquivos: {str(e)}', 
                'tipo_mensagem': 'erro'
            })

    # 3. Tratamento de "Não Encontrado"
    if request.method == 'POST' and not lista_boletos:
        return render(request, 'solicitacoes/boletos.html', {
            'mensagem': f'Boleto da nota "{numero_nota}" não encontrado na pasta 2026.',
            'tipo_mensagem': 'erro',
            'numero_nota': numero_nota
        })

    # 4. Retorno Sucesso ou GET inicial
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
            plantao.observacoes += f"\n[CONFIRMAÇÃO]: {obs}"
        
        plantao.save()
        messages.success(request, f"Plantão de {plantao.nome_cliente} confirmado!")
        return redirect('plantao_list')

    busca = request.GET.get('busca')
    vendedor_id = request.GET.get('vendedor')
    ocorrencia = request.GET.get('ocorrencia')
    data_f = request.GET.get('data')

    plantoes = Plantao.objects.all().order_by('-data_solicitacao')

    if busca:
        plantoes = plantoes.filter(Q(nome_cliente__icontains=busca) | Q(codigo_cliente__icontains=busca))
    if vendedor_id:
        plantoes = plantoes.filter(vendedor_id=vendedor_id)
    if ocorrencia:
        plantoes = plantoes.filter(ocorrencia=ocorrencia)
    if data_f:
        plantoes = plantoes.filter(data_solicitacao__date=data_f)

    vVendedores = User.objects.all()
    return render(request, 'solicitacoes/plantao_list.html', {'plantoes': plantoes, 'vendedores': vVendedores})

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

def novo_plantao(request):
    if request.method == 'POST':

        vendedor_id = request.POST.get('vendedor')
        vendedor_instancia = request.user
        
        Plantao.objects.create(
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
            vendedor=vendedor_instancia,
            tipo=request.POST.get('tipo'),
            ocorrencia=request.POST.get('ocorrencia'),
            ocorrencia_outro=request.POST.get('ocorrencia_outro'),
            observacoes=request.POST.get('observacoes'),
            taxa=(request.POST.get('taxa') == 'SIM'),
            valor_taxa=request.POST.get('valor_taxa').replace('R$', '').replace('.', '').replace(',', '.').strip(),
            horario=request.POST.get('horario')
        )
        
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

    bonificacoes = Bonificacao.objects.all().order_by('-data_solicitacao')

    if plataforma_filtro:
        bonificacoes = bonificacoes.filter(plataforma=plataforma_filtro)
    
    eh_vendedor = request.user.groups.filter(name='Vendedores').exists()

    if eh_vendedor:
        bonificacoes = bonificacoes.filter(vendedor=request.user)

    if eh_vendedor:
        usuarios = User.objects.filter(pk=request.user.pk)
    else:
        usuarios = User.objects.filter(groups__name='Vendedores', is_active=True).order_by('first_name')

    if request.user.groups.filter(name='Vendedores').exists():
        bonificacoes = bonificacoes.filter(vendedor=request.user)

    if busca:
        bonificacoes = bonificacoes.filter(
            Q(cliente_razao_social__icontains=busca) | 
            Q(cliente_cpf_cnpj__icontains=busca)
        )

    if tipo:
        bonificacoes = bonificacoes.filter(tipo=tipo)

    if vendedor_id:
        if eh_vendedor:
            bonificacoes = bonificacoes.filter(vendedor=request.user)
        else:
            bonificacoes = bonificacoes.filter(vendedor_id=vendedor_id)

    if status:
        bonificacoes = bonificacoes.filter(status=status)

    if data_param:
        bonificacoes = bonificacoes.filter(data_solicitacao__date=data_param)

    context = {
        'bonificacoes': bonificacoes,
        'usuarios': usuarios,
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
                messages.warning(request, "Nenhum acordo vigente encontrado para este cliente. A solicitação seguirá para aprovação manual.")
            else:
                realizado_protheus = calcular_realizado_protheus(cliente_cod, cliente_loja, acordo.vigencia_inicio, acordo.vigencia_fim)
                
                reservado_local = BonificacaoItem.objects.filter(
                    bonificacao__cliente_codigo=cliente_cod,
                    bonificacao__tipo='ACORDO_COMERCIAL',
                    bonificacao__status__in=['APROVADO', 'CONCLUIDO'],
                    bonificacao__data_solicitacao__range=(acordo.vigencia_inicio, acordo.vigencia_fim)
                ).aggregate(total=Sum('valor_total') if acordo.tipo_acordo == 'valor' else Sum('quantidade'))['total'] or 0

                if acordo.tipo_acordo == 'valor':
                    objetivo = float(acordo.valor_acordo)
                    consumido = float(realizado_protheus['valor']) + float(reservado_local)
                    disponivel = objetivo - consumido
                    solicitado = total_solicitacao
                    unidade = "R$"
                else:
                    objetivo = sum(item.qtd_faturada for item in acordo.itens.all())
                    consumido = realizado_protheus['qtd'] + reservado_local
                    disponivel = objetivo - consumido
                    solicitado = total_qtd_solicitacao
                    unidade = "UN"

                if solicitado <= disponivel:
                    status_final = 'APROVADO'
                    messages.success(request, f"Bonificação aprovada automaticamente! Saldo restante: {unidade} {disponivel - solicitado:,.2f}")
                else:
                    messages.error(request, f"Saldo insuficiente no acordo! Disponível: {unidade} {disponivel:,.2f}. Solicitado: {unidade} {solicitado:,.2f}")
                    return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

        
        elif tipo == 'VERBA_VENDEDOR':
            # Garante que estamos pegando a verba EXATA do mês e ano corrente
            verba_configurada = VerbaMensal.objects.filter(
                vendedor=request.user, 
                mes_referencia=hoje.month, 
                ano_referencia=hoje.year
            ).first()

            if not verba_configurada:
                messages.error(request, f"Não existe verba cadastrada para o período {hoje.month}/{hoje.year}.")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

            # 1. Validação de Limite por Cliente (Consumo mensal por CNPJ)
            limite_valor_cliente = float(verba_configurada.limite_por_cliente) # Use o campo calculado do model se existir
            
            ja_gasto_cliente = Bonificacao.objects.filter(
                vendedor=request.user, 
                cliente_cpf_cnpj=cliente_cnpj,
                data_solicitacao__month=hoje.month, 
                data_solicitacao__year=hoje.year,
                # Importante: Incluir PENDENTES para não furar o teto
                status__in=['APROVADO', 'PENDENTE', 'CONCLUIDO']
            ).aggregate(total=Sum('itens__valor_total'))['total'] or 0

            if (float(ja_gasto_cliente) + total_solicitacao) > limite_valor_cliente:
                messages.error(request, f"Limite por cliente excedido! O máximo para este cliente é R$ {limite_valor_cliente:,.2f}")
                return render(request, 'solicitacoes/bonificacao_form.html', {'dados': request.POST})

            # 2. Validação do Saldo Global do Vendedor (Consumo total do mês)
            # Aqui é onde o erro do mês passado geralmente acontece:
            gastos_totais_mes = Bonificacao.objects.filter(
                vendedor=request.user, 
                tipo='VERBA_VENDEDOR',
                data_solicitacao__month=hoje.month, # Filtro estrito de mês
                data_solicitacao__year=hoje.year,   # Filtro estrito de ano
                status__in=['APROVADO', 'PENDENTE', 'CONCLUIDO'] # Considere pendentes!
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
                    if tipo == 'SAC':
                        messages.info(request, "Solicitação de SAC enviada para aprovação.")
                    elif tipo == 'ACORDO_COMERCIAL':
                        messages.info(request, "E-mail de solicitação enviado para a equipe de aprovação de acordos.")
                    elif tipo == 'NEGOCIACAO_ESPECIAL':
                        messages.info(request, "E-mail de solicitação enviado para aprovação.")
            except Exception as email_err:
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
        
    return redirect('plantao_list') # Substitua pelo nome da sua URL de listagem

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