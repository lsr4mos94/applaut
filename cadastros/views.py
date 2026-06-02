import os
import datetime
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.db import connections
from django.db.models import Q, Sum
from usuarios.models import Perfil
from solicitacoes.models import Bonificacao, BonificacaoItem
from .models import (
    VerbaMensal, 
    AcordoComercial, 
    AcordoItem, 
    Cadastro, 
    AnexoCadastro
)

@login_required
def verbas_mensais(request):
    vendedores_select = User.objects.filter(is_active=True).order_by('first_name')

    verbas = VerbaMensal.objects.select_related('vendedor', 'vendedor__perfil').all().order_by('-data_criacao')

    if request.user.groups.filter(name='Vendedores').exists():
        verbas = verbas.filter(vendedor=request.user)
        vendedores_select = vendedores_select.filter(id=request.user.id)

    vendedor_id = request.GET.get('vendedor')
    mes = request.GET.get('mes')
    ano = request.GET.get('ano')
    busca = request.GET.get('busca')

    if vendedor_id:
        verbas = verbas.filter(vendedor_id=vendedor_id)

    if mes:
        verbas = verbas.filter(mes_referencia=mes)

    if ano:
        verbas = verbas.filter(ano_referencia=ano)

    if busca:
        if busca.isdigit():
            verbas = verbas.filter(
                Q(id=busca) | 
                Q(vendedor__perfil__codigo_vendedor__icontains=busca)
            )
        else:
            verbas = verbas.filter(
                Q(vendedor__first_name__icontains=busca) | 
                Q(vendedor__last_name__icontains=busca)
            )

    paginator = Paginator(verbas, 10)
    page_number = request.GET.get('page')
    verbas_paginadas = paginator.get_page(page_number)

    context = {
        'verbas': verbas_paginadas,
        'vendedores': vendedores_select,
        'meses': VerbaMensal.MESES_CHOICES
    }
    return render(request, 'cadastros/verbas.html', context)

def buscar_vendedor_por_codigo(request):
    codigo = request.GET.get('codigo')
    try:
        perfil = Perfil.objects.get(codigo_vendedor=codigo)
        data = {
            'sucesso': True,
            'nome': f"{perfil.usuario.first_name} {perfil.usuario.last_name}",
            'id_usuario': perfil.usuario.id
        }
    except Perfil.DoesNotExist:
        data = {'sucesso': False}
    return JsonResponse(data)

@login_required
def salvar_verba(request):
    if request.method == 'POST':
        vendedor_id = request.POST.get('vendedor_id')
        mes = request.POST.get('mes')
        ano = request.POST.get('ano')
        valor = request.POST.get('valor')
        percentual = request.POST.get('percentual_limite', 100)

        VerbaMensal.objects.create(
            vendedor_id=vendedor_id,
            mes_referencia=mes,
            ano_referencia=ano,
            valor=valor,
            percentual_limite_por_cliente=percentual,
            usuario_cadastro=request.user
        )
        messages.success(request, "Verba cadastrada com sucesso!")
    return redirect('verbas_mensais')

def editar_verba(request, pk):
    verba = get_object_or_404(VerbaMensal, pk=pk)
    
    if request.method == 'POST':
        novo_valor = float(request.POST.get('valor').replace(',', '.'))
        valor_ja_gasto = float(verba.valor_utilizado)
        
        if novo_valor < valor_ja_gasto:
            messages.error(request, f"Erro: O vendedor já utilizou R$ {valor_ja_gasto:.2f} em bonificações. Você não pode reduzir a verba para menos que isso.")
            return redirect('verbas_mensais')
        
        verba.valor = novo_valor
        verba.mes_referencia = request.POST.get('mes')
        verba.ano_referencia = request.POST.get('ano')
        verba.percentual_limite_por_cliente = request.POST.get('percentual_limite')
        verba.save()
        
        messages.success(request, "Verba atualizada com sucesso!")
        return redirect('verbas_mensais')

@login_required
def excluir_verba(request, pk):
    verba = get_object_or_404(VerbaMensal, pk=pk)
    if request.method == 'POST':
        verba.delete()
        messages.success(request, "Lançamento excluído!")
    return redirect('verbas_mensais')

@login_required
def acordos_comerciais(request):
    busca = request.GET.get('busca')
    data_fim = request.GET.get('data_fim')
    status_filtro = request.GET.get('status')

    acordos_queryset = AcordoComercial.objects.all().prefetch_related('itens').order_by('-data_acordo')

    if busca:
        acordos_queryset = acordos_queryset.filter(
            Q(cliente_nome_fantasia__icontains=busca) |
            Q(cliente_codigo__icontains=busca)
        )

    if data_fim:
        acordos_queryset = acordos_queryset.filter(vigencia_fim__lte=data_fim)

    todos_acordos = list(acordos_queryset)

    if status_filtro and status_filtro.strip() in ['Ativo', 'Encerrado']:
        status_limpo = status_filtro.strip()
        todos_acordos = [
            acordo for acordo in todos_acordos 
            if acordo.status_atual == status_limpo
        ]

    paginator = Paginator(todos_acordos, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'acordos': page_obj,
        'request': request
    }

    return render(request, 'cadastros/acordos.html', context)

def salvar_acordo(request):
    if request.method == 'POST':
        try:
            acordo = AcordoComercial(
                cliente_codigo=request.POST.get('cliente_codigo'),
                cliente_loja=request.POST.get('cliente_loja'),
                cliente_nome=request.POST.get('cliente_nome'),
                data_acordo=timezone.now().date(),
                vigencia_inicio=request.POST.get('vigencia_inicio'),
                vigencia_fim=request.POST.get('vigencia_fim'),
                tipo_acordo=request.POST.get('tipo_acordo'),
                valor_acordo=request.POST.get('valor_acordo') or None,
                justificativa=request.POST.get('justificativa'),
                usuario_cadastro=request.user
            )
            acordo.save()

            if acordo.tipo_acordo == 'produto':
                codigos = request.POST.getlist('prod_codigo[]')
                descricoes = request.POST.getlist('prod_desc[]')
                quantidades = request.POST.getlist('prod_qtd[]')

                for i in range(len(codigos)):
                    AcordoItem.objects.create(
                        acordo=acordo,
                        produto_codigo=codigos[i],
                        produto_descricao=descricoes[i],
                        qtd_faturada=quantidades[i] if i < len(quantidades) and quantidades[i] else 0
                    )

            messages.success(request, "Acordo salvo com sucesso!")
        except Exception as e:
            messages.error(request, f"Erro ao salvar: {e}")
        
        return redirect('acordos_comerciais')

@login_required
def excluir_acordo(request, pk):
    if request.method == 'POST':
        acordo = get_object_or_404(AcordoComercial, pk=pk)
        nome_cliente = acordo.cliente_nome
        acordo.delete()
        messages.success(request, f"Acordo de '{nome_cliente}' excluído com sucesso.")
    
    return redirect('acordos_comerciais')

@login_required
def lista_cadastros(request):
    busca = request.GET.get('busca')
    data_filtro = request.GET.get('data')
    vendedor_id = request.GET.get('vendedor')
    status_filtro = request.GET.get('status')

    pode_ver_tudo = request.user.groups.filter(
        name__in=['Cadastro', 'Contas a Receber', 'Gestão Comercial']
    ).exists()

    if pode_ver_tudo:
        cadastros_list = Cadastro.objects.all().order_by('-data_cadastro')
        usuarios = User.objects.filter(is_active=True).order_by('first_name')
    else:
        cadastros_list = Cadastro.objects.filter(vendedor=request.user).order_by('-data_cadastro')
        usuarios = User.objects.filter(id=request.user.id)

    if busca:
        cadastros_list = cadastros_list.filter(
            Q(razao_social__icontains=busca) | Q(cgc__icontains=busca)
        )
    if data_filtro:
        cadastros_list = cadastros_list.filter(data_cadastro__date=data_filtro)
    if vendedor_id:
        cadastros_list = cadastros_list.filter(vendedor_id=vendedor_id)
    if status_filtro:
        cadastros_list = cadastros_list.filter(situacao=status_filtro)

    paginator = Paginator(cadastros_list, 10)
    page_number = request.GET.get('page')
    cadastros = paginator.get_page(page_number)

    context = {
        'cadastros': cadastros,
        'usuarios': usuarios,
        'user_no_grupo_cadastro': request.user.groups.filter(name='Cadastro').exists(),
        'user_no_grupo_financeiro': request.user.groups.filter(name='Contas a Receber').exists(),
    }
    return render(request, 'cadastros/cadastros.html', context)

@login_required
def criar_cadastro(request):
    if request.method == 'POST':
        try:
            cadastro = Cadastro.objects.create(
                vendedor=request.user,
                plataforma=request.POST.get('plataforma'),
                tipo_cliente=request.POST.get('tipo_cliente'),
                razao_social=request.POST.get('razao_social'),
                nome_fantasia=request.POST.get('nome_fantasia'),
                cgc=request.POST.get('cgc'),
                inscricao_estadual=request.POST.get('inscricao_estadual'),
                email=request.POST.get('email'),
                telefone=request.POST.get('telefone'),
                cep=request.POST.get('cep'),
                estado=request.POST.get('estado'),
                cidade=request.POST.get('cidade'),
                bairro=request.POST.get('bairro'),
                endereco=request.POST.get('endereco'),
                numero=request.POST.get('numero'),
                complemento=request.POST.get('complemento'),
                
                entrega_cep=request.POST.get('entrega_cep'),
                entrega_estado=request.POST.get('entrega_estado'),
                entrega_cidade=request.POST.get('entrega_cidade'),
                entrega_bairro=request.POST.get('entrega_bairro'),
                entrega_endereco=request.POST.get('entrega_endereco'),
                entrega_numero=request.POST.get('entrega_numero'),
                entrega_complemento=request.POST.get('entrega_complemento'),
                
                grupo_cliente=request.POST.get('grupo_cliente'),
                horario_entrega=request.POST.get('horario_entrega'),
                condicao_pagamento=request.POST.get('cond_pagto'),
                condicao_pagamento_outro=request.POST.get('cond_pagto_outro'),
                
                socio_nome=request.POST.get('socio_nome'),
                socio_cpf=request.POST.get('socio_cpf'),
                socio_cep=request.POST.get('socio_cep'),
                socio_estado=request.POST.get('socio_estado'),
                socio_cidade=request.POST.get('socio_cidade'),
                socio_bairro=request.POST.get('socio_bairro'),
                socio_endereco=request.POST.get('socio_endereco'),
                socio_numero=request.POST.get('socio_numero'),
                socio_complemento=request.POST.get('socio_complemento'),
                
                finan_nome=request.POST.get('finan_nome'),
                finan_cpf=request.POST.get('finan_cpf'),
                compra_nome=request.POST.get('compra_nome'),
                compra_cpf=request.POST.get('compra_cpf'),
                situacao='PENDENTE'
            )

            arquivos = {
                'Cartão CNPJ': request.FILES.get('anexo_cnpj'),
                'Contrato Social': request.FILES.get('anexo_contrato'),
                'Comprovante Endereço': request.FILES.get('anexo_endereco'),
                'Identidade Sócio': request.FILES.get('anexo_identidade'),
            }

            for nome, arquivo in arquivos.items():
                if arquivo:
                    AnexoCadastro.objects.create(cadastro=cadastro, nome=nome, arquivo=arquivo)

            email_enviado = enviar_email_fluxo(cadastro, 'novo_cadastro')

            if email_enviado:
                messages.success(request, "Cadastro realizado com sucesso! A equipe de cadastro foi notificada.")
            else:
                messages.warning(request, "Cadastro realizado, mas houve um erro temporário no servidor de e-mail. A equipe visualizará pelo painel.")

            return redirect('lista_cadastros')
        
        except Exception as e:
            messages.error(request, f"Erro ao processar cadastro: {str(e)}")
            return render(request, 'cadastros/novo_cadastro.html', {'dados': request.POST})
        
    return render(request, 'cadastros/novo_cadastro.html')

@login_required
def detalhes_cadastro(request, pk):
    cadastro = get_object_or_404(Cadastro.objects.prefetch_related('anexos'), pk=pk)
    return render(request, 'cadastros/detalhes_cadastro.html', {'cadastro': cadastro})

@login_required
def editar_cadastro(request, pk):
    cadastro = get_object_or_404(Cadastro, pk=pk)

    if cadastro.vendedor != request.user or cadastro.situacao not in ['PENDENTE', 'REJEITADO']:
        messages.error(request, "Este cadastro não pode ser editado pois já foi aprovado ou pertence a outro vendedor.")
        return redirect('lista_cadastros')

    if request.method == 'POST':
        try:
            cadastro.plataforma = request.POST.get('plataforma')
            cadastro.tipo_cliente = request.POST.get('tipo_cliente')
            cadastro.razao_social = request.POST.get('razao_social')
            cadastro.nome_fantasia = request.POST.get('nome_fantasia')
            cadastro.cgc = request.POST.get('cgc')
            cadastro.inscricao_estadual = request.POST.get('inscricao_estadual')
            cadastro.email = request.POST.get('email')
            cadastro.telefone = request.POST.get('telefone')
            cadastro.cep = request.POST.get('cep')
            cadastro.estado = request.POST.get('estado')
            cadastro.cidade = request.POST.get('cidade')
            cadastro.bairro = request.POST.get('bairro')
            cadastro.endereco = request.POST.get('endereco')
            cadastro.numero = request.POST.get('numero')
            cadastro.complemento = request.POST.get('complemento')
            
            cadastro.entrega_cep = request.POST.get('entrega_cep')
            cadastro.entrega_estado = request.POST.get('entrega_estado')
            cadastro.entrega_cidade = request.POST.get('entrega_cidade')
            cadastro.entrega_bairro = request.POST.get('entrega_bairro')
            cadastro.entrega_endereco = request.POST.get('entrega_endereco')
            cadastro.entrega_numero = request.POST.get('entrega_numero')
            cadastro.entrega_complemento = request.POST.get('entrega_complemento')
            
            cadastro.grupo_cliente = request.POST.get('grupo_cliente')
            cadastro.horario_entrega = request.POST.get('horario_entrega')
            cadastro.condicao_pagamento = request.POST.get('cond_pagto')
            cadastro.condicao_pagamento_outro = request.POST.get('cond_pagto_outro')
            
            cadastro.socio_nome = request.POST.get('socio_nome')
            cadastro.socio_cpf = request.POST.get('socio_cpf')
            cadastro.socio_cep = request.POST.get('socio_cep')
            cadastro.socio_estado = request.POST.get('socio_estado')
            cadastro.socio_cidade = request.POST.get('socio_cidade')
            cadastro.socio_bairro = request.POST.get('socio_bairro')
            cadastro.socio_endereco = request.POST.get('socio_endereco')
            cadastro.socio_numero = request.POST.get('socio_numero')
            cadastro.socio_complemento = request.POST.get('socio_complemento')
            
            cadastro.finan_nome = request.POST.get('finan_nome')
            cadastro.finan_cpf = request.POST.get('finan_cpf')
            cadastro.compra_nome = request.POST.get('compra_nome')
            cadastro.compra_cpf = request.POST.get('compra_cpf')

            cadastro.situacao = 'PENDENTE'
            cadastro.observacoes = ""
            cadastro.save()

            arquivos_novos = {
                'Cartão CNPJ': request.FILES.get('anexo_cnpj'),
                'Contrato Social': request.FILES.get('anexo_contrato'),
                'Comprovante Endereço': request.FILES.get('anexo_endereco'),
                'Identidade Sócio': request.FILES.get('anexo_identidade'),
            }

            for nome_doc, arquivo_novo in arquivos_novos.items():
                if arquivo_novo:
                    anexo_antigo = AnexoCadastro.objects.filter(cadastro=cadastro, nome=nome_doc).first()
                    if anexo_antigo:
                        if anexo_antigo.arquivo and os.path.isfile(anexo_antigo.arquivo.path):
                            try:
                                os.remove(anexo_antigo.arquivo.path)
                            except Exception as e:
                                print(f"Erro ao deletar arquivo físico: {e}")
                        anexo_antigo.delete()
                    AnexoCadastro.objects.create(cadastro=cadastro, nome=nome_doc, arquivo=arquivo_novo)

            email_ok = enviar_email_fluxo(cadastro, 'novo_cadastro')

            if email_ok:
                messages.success(request, f"Cadastro de {cadastro.razao_social} atualizado! A equipe foi notificada por e-mail.")
            else:
                messages.warning(request, f"Cadastro de {cadastro.razao_social} atualizado, mas ocorreu um erro ao enviar o e-mail de notificação.")
            
            return redirect('lista_cadastros')

        except Exception as e:
            messages.error(request, f"Erro ao atualizar cadastro: {str(e)}")
    
    return render(request, 'cadastros/novo_cadastro.html', {
        'cadastro': cadastro,
        'editando': True
    })

def enviar_email_fluxo(cadastro, fase):
 
    email_cadastro_equipe = ['cadastroclientes@lautbeer.com.br']
    email_financeiro_equipe = ['cobranca@lautbeer.com.br']
    email_vendedor = [cadastro.vendedor.email]

    contexto = {'cadastro': cadastro, 'fase': fase}
    destinatarios = []
    template_path = ""
    assunto = ""

    if fase == 'novo_cadastro':
        assunto = f"🚀 NOVO CADASTRO: {cadastro.razao_social}"
        destinatarios = email_cadastro_equipe
        template_path = 'emails/solicitacao_cadastro.html'
    elif fase == 'financeiro':
        assunto = f"💰 ANÁLISE FINANCEIRA: {cadastro.razao_social}"
        destinatarios = email_financeiro_equipe
        template_path = 'emails/solicitacao_financeiro.html'
    elif fase == 'finalizado':
        assunto = f"✅ CADASTRO LIBERADO: {cadastro.razao_social}"
        destinatarios = email_vendedor
        template_path = 'emails/cadastro_finalizado.html'
    elif fase == 'rejeitado':
        assunto = f"❌ CADASTRO RECUSADO: {cadastro.razao_social}"
        destinatarios = email_vendedor
        template_path = 'emails/cadastro_rejeitado.html'

    try:
        html_content = render_to_string(template_path, contexto)
        email = EmailMessage(
            assunto,
            html_content,
            settings.DEFAULT_FROM_EMAIL,
            destinatarios
        )
        email.content_subtype = "html"
        
        email.send(fail_silently=False)
        return True
    except Exception:
        return False
    
@login_required
def processar_status(request, pk):
    if request.method == 'POST':
        cadastro = get_object_or_404(Cadastro, pk=pk)
        acao = request.POST.get('acao')
        observacao = request.POST.get('observacao', '')

        usuario_eh_cadastro = request.user.groups.filter(name='Cadastro').exists()
        usuario_eh_financeiro = request.user.groups.filter(name='Contas a Receber').exists()
        
        email_ok = True

        if acao == 'aprovar':
            if usuario_eh_cadastro and cadastro.situacao == 'PENDENTE':
                cadastro.situacao = 'CADASTRADO'
                cadastro.observacoes = observacao
                email_ok = enviar_email_fluxo(cadastro, 'financeiro')
                if email_ok:
                    messages.success(request, "Cadastro aprovado! Enviado para análise do Financeiro.")
                
            elif usuario_eh_financeiro and cadastro.situacao == 'CADASTRADO':
                cadastro.situacao = 'LIBERADO'
                cadastro.observacoes = observacao
                email_ok = enviar_email_fluxo(cadastro, 'finalizado')
                if email_ok:
                    messages.success(request, "Cadastro liberado com sucesso!")

        elif acao == 'reprovar':
            cadastro.situacao = 'REJEITADO'
            cadastro.observacoes = observacao
            email_ok = enviar_email_fluxo(cadastro, 'rejeitado')
            if email_ok:
                messages.warning(request, "Cadastro reprovado e vendedor notificado.")

        if not email_ok:
            messages.error(request, f"O cadastro de '{cadastro.razao_social}' foi processado no sistema, mas ocorreu um erro ao enviar a notificação por e-mail.")

        cadastro.save()
        return redirect('lista_cadastros')

@login_required
def api_historico_acordo(request, acordo_id):
    try:
        acordo = AcordoComercial.objects.get(id=acordo_id)
        itens_acordados = acordo.itens.all()
        
        cliente_cod = acordo.cliente_codigo
        cliente_loja = acordo.cliente_loja

        # 1. PASSO DA NOVA REGRA: Buscar os números de pedidos vinculados a este acordo no Applaut
        # Buscamos os pedidos das bonificações que possuem itens amarrados a este acordo
        pedidos_vinculados = list(Bonificacao.objects.filter(
            itens__acordo_vinculado=acordo,
            status__in=['APROVADO', 'CONCLUIDO']
        ).exclude(pedido_protheus__isnull=True).exclude(pedido_protheus='').values_list('pedido_protheus', flat=True).distinct())

        historico_nfs = []
        realizado_acumulado = 0.0

        # Se nenhum pedido foi gerado ainda para este acordo, não há faturamento no Protheus
        if not pedidos_vinculados:
            objetivo = float(acordo.valor_acordo or 0) if acordo.tipo_acordo == 'valor' else float(sum(item.qtd_faturada for item in itens_acordados))
            label_unidade = f"R$ 0.00 de R$ {objetivo:,.2f}" if acordo.tipo_acordo == 'valor' else f"0 de {int(objetivo)} UN"
            return JsonResponse({'porcentagem': 0.0, 'label_progresso': label_unidade, 'nfs': []})

        # 2. Query do Protheus simplificada (Filtra direto pelos números dos pedidos)
        bases_de_consulta = {
            'protheus_ciec': ['SD2010', 'SD2020'],
            'protheus_wrp': ['SD2010']
        }

        placeholders_pedidos = ', '.join(['%s'] * len(pedidos_vinculados))
        query_base = f"""
            SELECT D2_DOC, D2_SERIE, D2_EMISSAO, D2_COD, B1_DESC, D2_QUANT, D2_TOTAL, D2_PEDIDO
            FROM {{tabela}} AS SD2
            INNER JOIN SF4{{empresa}} AS SF4 ON SF4.F4_FILIAL = SD2.D2_FILIAL AND SF4.F4_CODIGO = SD2.D2_TES AND SF4.D_E_L_E_T_ <> '*'
            INNER JOIN SB1{{empresa}} AS SB1 ON SB1.B1_FILIAL = SD2.D2_FILIAL AND SB1.B1_COD = SD2.D2_COD AND SB1.D_E_L_E_T_ <> '*'
            WHERE SD2.D_E_L_E_T_ <> '*' 
            AND SD2.D2_CLIENTE = %s AND SD2.D2_LOJA = %s
            AND SF4.F4_BONIF = 'S' AND SD2.D2_TES <> '802'
            AND SD2.D2_PEDIDO IN ({placeholders_pedidos})
        """

        todas_linhas_protheus = []
        for db_alias, tabelas in bases_de_consulta.items():
            for tabela in tabelas:
                empresa_sufixo = tabela[-3:] 
                
                # Parâmetros: cliente, loja + lista de pedidos salvos
                params = [cliente_cod, cliente_loja] + pedidos_vinculados

                with connections[db_alias].cursor() as cursor:
                    cursor.execute(query_base.format(tabela=tabela, empresa=empresa_sufixo), params)
                    rows = cursor.fetchall()
                    for row in rows:
                        todas_linhas_protheus.append(row)

        # Ordena as notas fiscais pela data de emissão
        todas_linhas_protheus.sort(key=lambda x: str(x[2]).strip())

        if acordo.tipo_acordo == 'valor':
            objetivo = float(acordo.valor_acordo or 0)
        else:
            objetivo = float(sum(item.qtd_faturada for item in itens_acordados))

        # 3. Loop de processamento leve (Sem lógica de outros_acordos)
        for row in todas_linhas_protheus:
            try:
                doc = str(row[0]).strip()
                serie = str(row[1]).strip()
                data_emissao_str = str(row[2]).strip()
                cod_prod_limpo = str(row[3]).strip()
                desc_prod = str(row[4]).strip()
                qtd = float(row[5] or 0)
                valor = float(row[6] or 0)

                incremento = valor if acordo.tipo_acordo == 'valor' else qtd

                if realizado_acumulado < objetivo:
                    if realizado_acumulado + incremento > objetivo:
                        fracao_restante = objetivo - realizado_acumulado
                        
                        if acordo.tipo_acordo == 'valor':
                            valor_exibir = fracao_restante
                            qtd_exibir = round((qtd * fracao_restante) / valor, 2) if valor > 0 else 0
                        else:
                            qtd_exibir = fracao_restante
                            valor_exibir = round((valor * fracao_restante) / qtd, 2) if qtd > 0 else 0

                        realizado_acumulado = objetivo
                        
                        historico_nfs.append({
                            'nf': f"{doc}/{serie}",
                            'data': f"{data_emissao_str[6:8]}/{data_emissao_str[4:6]}/{data_emissao_str[0:4]}",
                            'produto': f"{cod_prod_limpo} - {desc_prod}",
                            'qtd': qtd_exibir,
                            'valor': valor_exibir
                        })
                    else:
                        realizado_acumulado += incremento
                        historico_nfs.append({
                            'nf': f"{doc}/{serie}",
                            'data': f"{data_emissao_str[6:8]}/{data_emissao_str[4:6]}/{data_emissao_str[0:4]}",
                            'produto': f"{cod_prod_limpo} - {desc_prod}",
                            'qtd': qtd,
                            'valor': valor
                        })
                else:
                    continue

            except Exception as e:
                print(f"Erro linha: {e}")
                continue

        historico_nfs.reverse()

        if acordo.tipo_acordo == 'valor':
            label_unidade = f"R$ {realizado_acumulado:,.2f} de R$ {objetivo:,.2f}"
        else:
            label_unidade = f"{int(realizado_acumulado)} de {int(objetivo)} UN"

        porcentagem = (realizado_acumulado / objetivo * 100) if objetivo > 0 else 0
        
        return JsonResponse({
            'porcentagem': round(porcentagem, 1),
            'label_progresso': label_unidade,
            'nfs': historico_nfs
        })

    except Exception as e:
        print(f"Erro Crítico API Histórico: {str(e)}")
        return JsonResponse({'error': str(e), 'nfs': []}, status=500)

@login_required
def historico_utilizacao_verba(request, verba_id):
    try:
        verba = get_object_or_404(VerbaMensal, id=verba_id)
        
        utilizacoes = Bonificacao.objects.filter(
            vendedor=verba.vendedor,
            tipo='VERBA_VENDEDOR',
            data_solicitacao__month=verba.mes_referencia,
            data_solicitacao__year=verba.ano_referencia
        ).exclude(status='PENDENTE').prefetch_related('itens')

        lista_dados = []
        total_acumulado = 0
        
        for bonif in utilizacoes:
            valor_bonif = bonif.itens.aggregate(total=Sum('valor_total'))['total'] or 0
            total_acumulado += float(valor_bonif)
            
            lista_dados.append({
                'id': bonif.id,
                'cliente': bonif.cliente_nome_fantasia,
                'valor': float(valor_bonif),
                'pedido': bonif.pedido_protheus or 'Pendente'
            })

        objetivo = float(verba.valor or 0)
        saldo = objetivo - total_acumulado
        porcentagem = (total_acumulado / objetivo * 100) if objetivo > 0 else 0

        def format_br(valor):
            return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        utilizado_str = format_br(total_acumulado)
        disponivel_str = format_br(saldo)

        label_personalizado = f"Utilizado: R$ {utilizado_str} | Disponível: R$ {disponivel_str}"

        return JsonResponse({
            'sucesso': True,
            'porcentagem': round(porcentagem, 1),
            'total_gasto': total_acumulado,
            'saldo': saldo,
            'registros': lista_dados,
            'label_progresso': label_personalizado
        })
    except Exception as e:
        return JsonResponse({'sucesso': False, 'erro': str(e)}, status=500)
    
@login_required
def api_acordos_vigentes(request):
    cliente_cod = request.GET.get('cliente')
    loja_cod = request.GET.get('loja', '01')

    if not cliente_cod:
        return JsonResponse([], safe=False)

    # Traz todos os acordos vinculados ao cliente e loja cadastrados
    acordos = AcordoComercial.objects.filter(
        cliente_codigo=cliente_cod,
        cliente_loja=loja_cod
    )

    resultado = []
    for acordo in acordos:
        produtos_permitidos = []
        total_saldo_produtos = 0 

        # Varre os itens calculando o saldo real disponível
        for item in acordo.itens.all():
            # CORREÇÃO: O limite total definido no acordo está salvo em qtd_faturada
            qtd_limite = item.qtd_faturada or 0
            
            # O consumo do que já foi retirado/solicitado deste acordo fica em qtd_bonificada
            qtd_utilizada = item.qtd_bonificada or 0
            
            # O saldo disponível é o limite total do contrato menos o que já usou
            saldo_disponivel_item = max(0, qtd_limite - qtd_utilizada)
            
            # Acumula o saldo total do acordo de produto
            total_saldo_produtos += saldo_disponivel_item

            produtos_permitidos.append({
                'codigo': item.produto_codigo,
                'descricao': item.produto_descricao,
                'saldo_item': float(saldo_disponivel_item)
            })

        # Define a descrição e o saldo de exibição conforme o tipo de acordo
        if acordo.tipo_acordo == 'produto':
            descricao_final = f"Acordo #{acordo.id} (Por Produto) - {acordo.cliente_nome}"
            saldo_exibicao = total_saldo_produtos  
        else:
            descricao_final = f"Acordo #{acordo.id} (Por Valor) - {acordo.cliente_nome}"
            saldo_exibicao = float(acordo.valor_acordo) if acordo.valor_acordo else 0.0

        resultado.append({
            'id': acordo.id,
            'descricao': descricao_final,
            'inicio': acordo.vigencia_inicio.strftime('%d/%m/%Y') if acordo.vigencia_inicio else '',
            'fim': acordo.vigencia_fim.strftime('%d/%m/%Y') if acordo.vigencia_fim else '',
            'tipo_acordo': acordo.tipo_acordo,
            'saldo': float(saldo_exibicao),
            'produtos_permitidos': produtos_permitidos
        })

    return JsonResponse(resultado, safe=False)