import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags
from django.db import connections
from django.db.models import Q
from .forms import SolicitacaoVerbaForm
from .models import SolicitacaoVerba
from django.core.paginator import Paginator
from django.conf import settings

logger = logging.getLogger(__name__)

def e_gestor(user):
    return user.groups.filter(name__in=['Gestão Financeira']).exists()

@login_required
def listar_solicitacoes_verba(request):
    if request.user.groups.filter(name__in=['Gestão Financeira', 'Contas a Pagar']).exists():
        solicitacoes_qs = SolicitacaoVerba.objects.all()
    else:
        solicitacoes_qs = SolicitacaoVerba.objects.filter(usuario_solicitante=request.user)

    busca = request.GET.get('busca')
    solicitante_id = request.GET.get('solicitante')
    data_filtro = request.GET.get('data')
    status_filtro = request.GET.get('status')

    if busca:
        solicitacoes_qs = solicitacoes_qs.filter(
            Q(id__icontains=busca) | 
            Q(fornecedor_cpf_cnpj__icontains=busca) |
            Q(fornecedor_nome_razao__icontains=busca)
        )
    if solicitante_id:
        solicitacoes_qs = solicitacoes_qs.filter(usuario_solicitante_id=solicitante_id)
    if data_filtro:
        solicitacoes_qs = solicitacoes_qs.filter(data_solicitacao__date=data_filtro)
    if status_filtro:
        solicitacoes_qs = solicitacoes_qs.filter(status=status_filtro)

    solicitacoes_qs = solicitacoes_qs.order_by('-id')

    paginator = Paginator(solicitacoes_qs, 10)
    page_number = request.GET.get('page')
    solicitacoes_paginadas = paginator.get_page(page_number)

    context = {
        'solicitacoes': solicitacoes_paginadas,
        'usuarios': User.objects.all().order_by('first_name'),
    }
    return render(request, 'adm/verba_list.html', context)

@login_required
def detalhes_solicitacao_verba(request, pk):
    solicitacao = get_object_or_404(SolicitacaoVerba, pk=pk)
    
    data = {
        'id': solicitacao.id,
        'fornecedor_nome_razao': solicitacao.fornecedor_nome_razao,
        'fornecedor_cpf_cnpj': solicitacao.fornecedor_cpf_cnpj,
        'valor': f"{solicitacao.valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        'produto_servico': solicitacao.produto_servico,
        'categoria': solicitacao.get_categoria_display(),
        'forma_pagamento': solicitacao.get_forma_pagamento_display(),
        'status': solicitacao.get_status_display(),
        'solicitante': solicitacao.usuario_solicitante.get_full_name() or solicitacao.usuario_solicitante.username,
        'usuario_aprovador': (solicitacao.usuario_aprovador.get_full_name() or solicitacao.usuario_aprovador.username) if solicitacao.usuario_aprovador else "",
        'data_solicitacao': solicitacao.data_solicitacao.strftime('%d/%m/%Y'),
        'data_vencimento': solicitacao.data_vencimento.strftime('%d/%m/%Y') if solicitacao.data_vencimento else "---",
        'data_aprovacao': solicitacao.data_aprovacao.strftime('%d/%m/%Y %H:%M') if solicitacao.data_aprovacao else "",
        'descricao': solicitacao.observacoes, 
        'obs_aprovacao': solicitacao.obs_aprovacao or "",
        'num_titulo': solicitacao.num_titulo or "",
    }
    return JsonResponse(data)

@login_required
@user_passes_test(e_gestor)
def decidir_verba(request, pk):
    if request.method == 'POST':
        solicitacao = get_object_or_404(SolicitacaoVerba, pk=pk)
        acao = request.POST.get('acao')
        observacao_gestor = request.POST.get('motivo') 
        
        mensagens_status = {
            'aprovar': 'aprovada',
            'reprovar': 'reprovada'
        }
        status_texto = mensagens_status.get(acao, acao)

        if acao == 'aprovar':
            solicitacao.status = 'APROVADO'
            solicitacao.usuario_aprovador = request.user
            solicitacao.data_aprovacao = timezone.now()
            if observacao_gestor:
                solicitacao.obs_aprovacao = observacao_gestor
            
            solicitacao.save()

            subject = f"Solicitação de Verba Aprovada: #{solicitacao.id}"
            template = 'emails/solicitacao_aprovada.html'
            destinatarios = ['contasapagar@lautbeer.com.br', 'alexsandra@lautbeer.com.br', 'keylla.oliveira@lautbeer.com.br']
            contexto = {
                'verba': solicitacao,
                'site_url': settings.SITE_URL,
            }

        elif acao == 'reprovar':
            solicitacao.status = 'REPROVADO'
            solicitacao.obs_aprovacao = observacao_gestor
            solicitacao.usuario_aprovador = request.user
            solicitacao.data_aprovacao = timezone.now()
            solicitacao.save()

            subject = f"Solicitação de Verba Recusada: #{solicitacao.id}"
            template = 'emails/solicitacao_recusada.html'
            destinatarios = [solicitacao.usuario_solicitante.email]
            contexto = {
                'verba': solicitacao,
                'site_url': settings.SITE_URL,
            }

        try:
            html_content = render_to_string(template, contexto)
            email = EmailMultiAlternatives(
                subject, 
                strip_tags(html_content), 
                settings.DEFAULT_FROM_EMAIL, 
                destinatarios
            )
            email.attach_alternative(html_content, "text/html")
            email.send()
            
            messages.success(request, f"Solicitação {status_texto} com sucesso!")
            
        except Exception as e:
            logger.error(f"Erro ao enviar e-mail: {e}")
            messages.warning(request, f"Ação realizada, mas o e-mail de notificação falhou.")

    return redirect('listar_solicitacoes_verba')

@login_required
def concluir_verba(request, pk):
    if request.method == 'POST':
        solicitacao = get_object_or_404(SolicitacaoVerba, pk=pk)
        num_titulo = request.POST.get('num_titulo')
        
        solicitacao.status = 'CONCLUIDO'
        solicitacao.save()

        try:
            contexto = {
                'verba': solicitacao,
                'site_url': settings.SITE_URL,
            }
            html_content = render_to_string('emails/solicitacao_finalizada.html', contexto)
            email = EmailMultiAlternatives(
                f"Verba Concluída: #{solicitacao.id}", 
                strip_tags(html_content), 
                settings.DEFAULT_FROM_EMAIL, 
                [solicitacao.usuario_solicitante.email]
            )
            email.attach_alternative(html_content, "text/html")
            email.send()
            messages.success(request, "Solicitação concluída e enviada ao solicitante!")
        except Exception as e:
            logger.error(f"Erro ao enviar e-mail de conclusão: {e}")
            messages.warning(request, "Status atualizado, mas e-mail falhou.")

    return redirect('listar_solicitacoes_verba')

@login_required
def nova_solicitacao_verba(request):
    if request.method == 'POST':
        try:
            v_raw = request.POST.get('valor', '0')
            v_limpo = v_raw.replace('R$', '').replace('.', '').replace(',', '.').strip()
            
            solicitacao = SolicitacaoVerba.objects.create(
                usuario_solicitante=request.user,
                fornecedor_codigo=request.POST.get('fornecedor_codigo', '').strip(),
                fornecedor_loja=request.POST.get('fornecedor_loja', '').strip(),
                fornecedor_nome_razao=request.POST.get('fornecedor_nome_razao'),
                fornecedor_cpf_cnpj=request.POST.get('fornecedor_cpf_cnpj'),
                produto_servico=request.POST.get('produto_servico'),
                categoria=request.POST.get('categoria'),
                forma_pagamento=request.POST.get('forma_pagamento'),
                valor=v_limpo,
                data_vencimento=request.POST.get('data_vencimento'),
                observacoes=request.POST.get('observacoes', ''),
                tem_documento=request.POST.get('tem_documento') == 'True',
                status='PENDENTE'
            )

            try:
                subject = f"Nova Solicitação de Verba: #{solicitacao.id} - {solicitacao.fornecedor_nome_razao}"
                
                contexto_email = {
                    'verba': solicitacao,
                    'site_url': settings.SITE_URL
                }
                
                html_content = render_to_string('emails/solicitacao_verba.html', contexto_email)
                
                email = EmailMultiAlternatives(
                    subject, 
                    strip_tags(html_content), 
                    settings.DEFAULT_FROM_EMAIL, 
                    ['controladoria@lautbeer.com.br', 'alexsandra@lautbeer.com.br', 'financeiro@lautbeer.com.br']
                )
                email.attach_alternative(html_content, "text/html")
                email.send()
                messages.success(request, f"Solicitação #{solicitacao.id} enviada para análise!")
            except Exception as e:
                logger.error(f"Erro ao enviar e-mail de nova solicitação: {e}")
                messages.warning(request, "Solicitação gravada, mas falha ao enviar e-mail de alerta.")
            
            return redirect('listar_solicitacoes_verba')
        except Exception as e: 
            messages.error(request, f"Erro ao gravar: {e}")

    context = {
        'categorias': SolicitacaoVerba.CATEGORIAS_CHOICES,
        'forma_pagamento': SolicitacaoVerba.FORMA_PAGAMENTO_CHOICES,
        'titulo': "Nova Solicitação de Verba",
        'site_url': settings.SITE_URL,
    }
    return render(request, 'adm/verba_form.html', context)

@login_required
def editar_solicitacao_verba(request, pk):
    solicitacao = get_object_or_404(SolicitacaoVerba, pk=pk)
    
    if solicitacao.usuario_solicitante != request.user:
        messages.error(request, "Você não tem permissão para alterar esta solicitação.")
        return redirect('listar_solicitacoes_verba')

    if solicitacao.status not in ['PENDENTE', 'REPROVADO']:
        messages.warning(request, f"Esta solicitação está com status {solicitacao.get_status_display()} e não pode mais ser alterada.")
        return redirect('listar_solicitacoes_verba')

    if request.method == 'POST':
        data = request.POST.copy()
        v_raw = data.get('valor', '0')
        data['valor'] = v_raw.replace('R$', '').replace('.', '').replace(',', '.').strip()
        
        form = SolicitacaoVerbaForm(data, request.FILES, instance=solicitacao)
        if form.is_valid():
            obj = form.save(commit=False)
            
            obj.status = 'PENDENTE'
            obj.usuario_aprovador = None
            obj.data_aprovacao = None
            obj.obs_aprovacao = ''
            obj.save()

            try:
                subject = f"Solicitação Atualizada: #{obj.id} - {obj.fornecedor_nome_razao}"
                html_content = render_to_string('emails/solicitacao_verba.html', {'verba': obj})
                email = EmailMultiAlternatives(
                    subject, 
                    strip_tags(html_content), 
                    settings.DEFAULT_FROM_EMAIL, 
                    ['lorrane.ramos@lautbeer.com.br']
                )
                email.attach_alternative(html_content, "text/html")
                email.send()
                messages.success(request, f"Solicitação #{obj.id} alterada e enviada para nova análise!")
            except Exception as e:
                logger.error(f"Erro ao enviar e-mail na edição: {e}")
                messages.warning(request, "Alteração salva, mas houve falha ao notificar a gestão.")
            
            return redirect('listar_solicitacoes_verba')
    else:
        form = SolicitacaoVerbaForm(instance=solicitacao)

    return render(request, 'adm/verba_form.html', {
        'form': form, 
        'solicitacao': solicitacao, 
        'titulo': "Editar Solicitação",
        'categorias': SolicitacaoVerba.CATEGORIAS_CHOICES,
        'forma_pagamento': SolicitacaoVerba.FORMA_PAGAMENTO_CHOICES
    })

@login_required
def excluir_solicitacao_verba(request, pk):
    if request.method == 'POST':
        solicitacao = get_object_or_404(SolicitacaoVerba, pk=pk)
        if solicitacao.status == 'PENDENTE' or request.user.is_superuser:
            solicitacao.delete()
            messages.success(request, "Excluído com sucesso.")
    return redirect('listar_solicitacoes_verba')

@login_required
def busca_fornecedor_protheus(request):
    termo = request.GET.get('q', '').strip().upper()
    if len(termo) < 3: return JsonResponse([], safe=False)
    
    config_busca = {'protheus_ciec': ['SA2010', 'SA2020'], 'protheus_wrp': ['SA2010']}
    query = "SELECT TOP 15 RTRIM(A2_COD), RTRIM(A2_LOJA), RTRIM(A2_NOME), RTRIM(A2_CGC) FROM {tabela} WHERE D_E_L_E_T_ <> '*' AND (A2_NOME LIKE %s OR A2_CGC LIKE %s OR A2_COD LIKE %s)"
    params = [f'%{termo}%', f'%{termo}%', f'%{termo}%']
    resultados = {}

    for db, tabelas in config_busca.items():
        if db not in connections: continue
        for tabela in tabelas:
            try:
                with connections[db].cursor() as cursor:
                    cursor.execute(query.format(tabela=tabela), params)
                    for row in cursor.fetchall():
                        chave = f"{row[3]}_{row[0]}_{row[1]}"
                        if chave not in resultados:
                            resultados[chave] = {'codigo': row[0], 'loja': row[1], 'nome': row[2], 'cnpj': row[3]}
            except Exception as e: 
                logger.error(f"Erro SQL: {e}")
    return JsonResponse(list(resultados.values()), safe=False)