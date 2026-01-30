import os
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from usuarios.models import Perfil
from .models import VerbaMensal, AcordoComercial, AcordoItem, Cadastro, AnexoCadastro
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from django.db import connections

@login_required
def verbas_mensais(request):
    if request.user.groups.filter(name='Vendedor').exists():
        verbas = VerbaMensal.objects.filter(vendedor=request.user).order_by('-data_criacao')
        vendedores = User.objects.filter(id=request.user.id)
    else:
        verbas = VerbaMensal.objects.all().order_by('-data_criacao')
        vendedores = User.objects.filter(groups__name='Vendedor')
    
    mes = request.GET.get('mes')
    vendedor_id = request.GET.get('vendedor')

    if mes:
        verbas = verbas.filter(mes_referencia=mes)
    
    if vendedor_id:
        verbas = verbas.filter(vendedor_id=vendedor_id)

    context = {
        'verbas': verbas,
        'vendedores': vendedores,
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
        # Novo campo capturado do formulário
        percentual = request.POST.get('percentual_limite', 100)

        VerbaMensal.objects.create(
            vendedor_id=vendedor_id,
            mes_referencia=mes,
            ano_referencia=ano,
            valor=valor,
            percentual_limite_por_cliente=percentual, # Salva o limite
            usuario_cadastro=request.user
        )
        messages.success(request, "Verba cadastrada com sucesso!")
    return redirect('verbas_mensais')

def editar_verba(request, pk):
    verba = get_object_or_404(VerbaMensal, pk=pk)
    
    if request.method == 'POST':
        novo_valor = float(request.POST.get('valor').replace(',', '.'))
        valor_ja_gasto = float(verba.valor_utilizado)
        
        # VALIDAÇÃO DE SEGURANÇA
        if novo_valor < valor_ja_gasto:
            messages.error(request, f"Erro: O vendedor já utilizou R$ {valor_ja_gasto:.2f} em bonificações. Você não pode reduzir a verba para menos que isso.")
            return redirect('verbas_mensais')
        
        # Se passar na validação, salva
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
    tipo_acordo = request.GET.get('tipo_acordo')

    acordos = AcordoComercial.objects.all()

    if busca:
        acordos = acordos.filter(
            Q(cliente_nome__icontains=busca) |
            Q(cliente_codigo__icontains=busca)
        )

    if data_fim:
        acordos = acordos.filter(vigencia_fim__lte=data_fim)

    if tipo_acordo:
        acordos = acordos.filter(tipo_acordo=tipo_acordo)

    acordos = acordos.order_by('-data_acordo')
    
    return render(request, 'cadastros/acordos.html', {'acordos': acordos})

def salvar_acordo(request):
    if request.method == 'POST':
        try:
            # 1. Criar o Cabeçalho do Acordo
            acordo = AcordoComercial(
                cliente_codigo=request.POST.get('cliente_codigo'),
                cliente_loja=request.POST.get('cliente_loja'),
                cliente_nome=request.POST.get('cliente_nome'),
                data_acordo=timezone.now().date(),
                vigencia_inicio=request.POST.get('vigencia_inicio'),
                vigencia_fim=request.POST.get('vigencia_fim'),
                tipo_acordo=request.POST.get('tipo_acordo'),
                valor_acordo=request.POST.get('valor_acordo') or None,
                usuario_cadastro=request.user
            )
            acordo.save()

            # 2. Processar os Itens (Produtos)
            if acordo.tipo_acordo == 'produto':
                codigos = request.POST.getlist('prod_codigo[]')
                descricoes = request.POST.getlist('prod_desc[]')
                # CAPTURA O NOME CORRETO QUE ESTÁ NO HTML (prod_qtd[])
                quantidades = request.POST.getlist('prod_qtd[]')

                for i in range(len(codigos)):
                    AcordoItem.objects.create(
                        acordo=acordo,
                        produto_codigo=codigos[i],
                        produto_descricao=descricoes[i],
                        # Salva a quantidade enviada no campo qtd_faturada (ou o que você usa no modal)
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

    if request.user.is_superuser:
        cadastros = Cadastro.objects.all()
    else:
        cadastros = Cadastro.objects.filter(vendedor=request.user)

    if busca:
        cadastros = cadastros.filter(razao_social__icontains=busca) | cadastros.filter(cgc__icontains=busca)
    if data_filtro:
        cadastros = cadastros.filter(data_cadastro__date=data_filtro)
    if vendedor_id:
        cadastros = cadastros.filter(vendedor_id=vendedor_id)
    if status_filtro:
        cadastros = cadastros.filter(situacao=status_filtro)

    usuarios = User.objects.filter(is_active=True).order_by('first_name')

    context = {
        'cadastros': cadastros,
        'usuarios': usuarios,
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
            print(f"--- ERRO NO CADASTRO: {str(e)} ---") 
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
        
#        if fase in ['novo_cadastro', 'financeiro']:
#            for anexo in cadastro.anexos.all():
#                if anexo.arquivo:
#                    email.attach_file(anexo.arquivo.path)
        
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
        usuario_eh_financeiro = request.user.groups.filter(name='Financeiro').exists()
        
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

def api_historico_acordo(request, acordo_id):
    try:
        acordo = AcordoComercial.objects.get(id=acordo_id)
        itens_acordados = acordo.itens.all()
        
        cliente_cod = acordo.cliente_codigo
        cliente_loja = acordo.cliente_loja
        d1 = acordo.vigencia_inicio.strftime('%Y%m%d')
        d2 = acordo.vigencia_fim.strftime('%Y%m%d')
        
        # Mapeamento das instâncias e suas respectivas tabelas de itens de nota (SD2)
        bases_de_consulta = {
            'protheus_ciec': ['SD2010', 'SD2020'],
            'protheus_wrp': ['SD2010']
        }

        query_base = """
            SELECT D2_DOC, D2_SERIE, D2_EMISSAO, D2_COD, D2_DESC, D2_QUANT, D2_TOTAL
            FROM {tabela} AS SD2
            INNER JOIN SF4{empresa} AS SF4 ON SF4.F4_CODIGO = SD2.D2_TES AND SF4.D_E_L_E_T_ <> '*'
            WHERE SD2.D_E_L_E_T_ <> '*' 
            AND SD2.D2_CLIENTE = %s AND SD2.D2_LOJA = %s
            AND SD2.D2_EMISSAO BETWEEN %s AND %s
            AND SF4.F4_BONIF = 'S' AND SD2.D2_TES <> '802'
            ORDER BY D2_EMISSAO DESC
        """

        historico_nfs = []
        realizado_valor = 0.0
        realizado_qtd = 0.0

        for db_alias, tabelas in bases_de_consulta.items():
            for tabela in tabelas:
                # Extrai o sufixo da empresa (010 ou 020) para bater com a SF4 correspondente
                empresa_sufixo = tabela[-3:] 
                
                with connections[db_alias].cursor() as cursor:
                    cursor.execute(query_base.format(tabela=tabela, empresa=empresa_sufixo), 
                                 [cliente_cod, cliente_loja, d1, d2])
                    
                    rows = cursor.fetchall()
                    for row in rows:
                        qtd = float(row[5])
                        valor = float(row[6])
                        
                        realizado_valor += valor
                        realizado_qtd += qtd
                        
                        historico_nfs.append({
                            'nf': f"{row[0].strip()}/{row[1].strip()}",
                            'data': row[2].strip(),
                            'produto': f"{row[3].strip()} - {row[4].strip()}",
                            'qtd': qtd,
                            'valor': valor
                        })

        # Lógica de cálculo de progresso
        if acordo.tipo_acordo == 'valor':
            objetivo = float(acordo.valor_acordo or 0)
            atual = realizado_valor
            label_unidade = f"R$ {atual:,.2f} de R$ {objetivo:,.2f}"
        else:
            # Soma a quantidade acordada de todos os itens vinculados
            objetivo = sum(item.qtd_faturada for item in itens_acordados)
            atual = realizado_qtd
            label_unidade = f"{int(atual)} de {int(objetivo)} UN"

        porcentagem = (atual / objetivo * 100) if objetivo > 0 else 0
        
        return JsonResponse({
            'porcentagem': round(porcentagem, 1),
            'label_progresso': label_unidade,
            'nfs': historico_nfs
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)