from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.conf import settings 
import os
import mimetypes 
from .forms import LoginForm, NovoCadastroForm
from .models import Cadastro, AnexoCadastro
from django.contrib import messages
from django.views.decorators.http import require_http_methods 
from django.urls import reverse 
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import PasswordResetConfirmView
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Q

@login_required
def inicio(request):
    return render(request, 'inicio.html')

def form(request):
    return render(request, 'form.html')

@login_required
def cadastros(request):
    is_gestor = request.user.groups.filter(name='Gestores').exists()

    if is_gestor:
        cadastros_query = Cadastro.objects.all()
        vendedores_disponiveis = User.objects.filter(groups__name='Vendedores').order_by('first_name', 'username')
    else:
        cadastros_query = Cadastro.objects.filter(vendedor=request.user)
        vendedores_disponiveis = None

    termo_busca = request.GET.get('busca', '').strip()
    if termo_busca:
        cadastros_query = cadastros_query.filter(
            Q(razao_social__icontains=termo_busca) |
            Q(cgc__icontains=termo_busca)
        )

    if is_gestor:
        vendedor_id = request.GET.get('vendedor', '')
        if vendedor_id:
            try:
                vendedor_id = int(vendedor_id)
                cadastros_query = cadastros_query.filter(vendedor_id=vendedor_id)
            except ValueError:
                pass

    situacao = request.GET.get('situacao', '')
    if situacao:
        cadastros_query = cadastros_query.filter(situacao_status=situacao)

    cadastros_query = cadastros_query.order_by('-data_cadastro')

    context = {
        'cadastros': cadastros_query,
        'vendedores_disponiveis': vendedores_disponiveis,
        'situacoes_disponiveis': [
            ('Pendente (Cadastro)', 'Pendente (Cadastro)'),
            ('Pendente (Financeiro)', 'Pendente (Financeiro)'),
            ('Aprovado', 'Aprovado'),
            ('Rejeitado', 'Rejeitado'),
        ],
        'termo_busca_selecionado': termo_busca,
        'vendedor_selecionado': request.GET.get('vendedor', ''),
        'situacao_selecionada': situacao,
        'is_gestor': is_gestor,
    }
    return render(request, 'cadastros.html', context)


@login_required
def novo_cadastro(request):
    return render(request, 'novo_cadastro.html')

def novo_cadastro_submit(request):

    if request.method == 'POST':
        form = NovoCadastroForm(request.POST, request.FILES)
        if form.is_valid():
            cadastro = form.save(commit=False)
            
            cadastro.status = 'pendente' 
            
            cadastro.vendedor = request.user 
            cadastro.save()

            anexo_mapping = {
                'cartaoCnpj': 'Cartão CNPJ',
                'contratoSocial': 'Contrato Social/Estatuto',
                'comprovanteEndereco': 'Comprovante de Endereço',
                'documentoSocio': 'Documento de Identificação do Sócio'
            }

            anexos_para_email_attachment = []
            anexos_para_email_context = []

            for input_name, description in anexo_mapping.items():
                if input_name in request.FILES:
                    uploaded_file = request.FILES[input_name]
                    anexo = AnexoCadastro.objects.create(
                        cadastro=cadastro,
                        arquivo=uploaded_file,
                        descricao=description
                    )
                    anexos_para_email_attachment.append(anexo)
                    
                    if anexo.arquivo:
                        filename = os.path.basename(anexo.arquivo.name)
                        anexos_para_email_context.append({'descricao': description, 'nome_arquivo': filename})
                    else:
                        anexos_para_email_context.append({'descricao': description, 'nome_arquivo': 'N/A'})

            confirm_url = request.build_absolute_uri(
                reverse('salesapp:cadastro_confirmar', args=[cadastro.id])
            )
            reject_url = request.build_absolute_uri(
                reverse('salesapp:cadastro_rejeitar', args=[cadastro.id])
            )

            email_context = {
                'cadastro': cadastro,
                'confirm_url': confirm_url,
                'reject_url': reject_url,
                'anexos_info': anexos_para_email_context
            }

            email_html_content = render_to_string('email_cadastro.html', email_context)

            #to_email_list = ['cadastroclientes@lautbeer.com.br']
            to_email_list = ['lorrane.ramos@lautbeer.com.br']

            #if request.user.is_authenticated and request.user.email:
            #    to_email_list.append(request.user.email)

            #bcc_email_list = ['lorrane.ramos@lautbeer.com.br']
           
            from_email = settings.DEFAULT_FROM_EMAIL
            subject = f'Cliente Pendente de Cadastro: {cadastro.razao_social}'

            email = EmailMessage(
                subject,
                email_html_content,
                from_email,
                to_email_list,
                #bcc=bcc_email_list
            )
            email.content_subtype = "html"
            
            for anexo_obj in anexos_para_email_attachment:
                try:
                    if anexo_obj.arquivo and os.path.exists(anexo_obj.arquivo.path):
                        with open(anexo_obj.arquivo.path, 'rb') as f:
                            filename = os.path.basename(anexo_obj.arquivo.name)
                            
                            content_type = None
                            if hasattr(anexo_obj.arquivo, 'file') and hasattr(anexo_obj.arquivo.file, 'content_type'):
                                content_type = anexo_obj.arquivo.file.content_type
                            elif hasattr(anexo_obj.arquivo, 'content_type'):
                                content_type = anexo_obj.arquivo.content_type
                            else:
                                content_type, _ = mimetypes.guess_type(filename)
                            
                            if not content_type:
                                content_type = 'application/octet-stream'
                            
                            email.attach(filename, f.read(), content_type)
                    else:
                        print(f"ATENÇÃO: Arquivo físico não encontrado ou anexo.arquivo é None para {anexo_obj.descricao}. Caminho: {anexo_obj.arquivo.path if anexo_obj.arquivo else 'N/A'}")
                except FileNotFoundError:
                    print(f"ATENÇÃO: Arquivo de anexo não encontrado no caminho: {anexo_obj.arquivo.path}")
                except Exception as e:
                    print(f"ERRO: Falha ao anexar arquivo {anexo_obj.arquivo.name}: {e}")

            try:
                email.send()
            except Exception as e:
                print(f"ERRO: Falha ao enviar e-mail 'email_cadastro.html': {e}")
                messages.error(request, "Erro ao enviar e-mail de novo cadastro. Verifique os logs.")


            return JsonResponse({'success': True, 'message': 'Cadastro enviado e e-mail disparado para aprovação.'})
        else:
            errors_dict = dict(form.errors)
            return JsonResponse({'success': False, 'errors': errors_dict}, status=400)
    else:
        form = NovoCadastroForm()
    return render(request, 'novo_cadastro.html', {'form': form})

@require_http_methods(["GET", "POST"])
def cadastro_confirmar(request, cadastro_id):
    cadastro = get_object_or_404(Cadastro, id=cadastro_id)

    if cadastro.status != 'pendente': 
        context = {'cadastro': cadastro}
        messages.info(request, f"O cadastro de '{cadastro.razao_social}' já foi processado e não pode ser aprovado novamente.")
        return render(request, 'cadastro_ja_processado.html', context)

    if request.method == 'GET':
        action_url = reverse('salesapp:cadastro_confirmar', args=[cadastro.id])
        return render(request, 'cadastro_confirmar.html', {'cadastro': cadastro, 'action_url': action_url})

    elif request.method == 'POST':
        cadastro.status = 'cadastrado' 
        cadastro.save()

        liberar_url = request.build_absolute_uri(
            reverse('salesapp:liberar_cadastro', args=[cadastro.id])
        )
        bloquear_url = request.build_absolute_uri(
            reverse('salesapp:bloquear_cadastro', args=[cadastro.id])
        )
        
        anexos_db = AnexoCadastro.objects.filter(cadastro=cadastro)

        anexos_para_email_context = []
        for anexo_obj in anexos_db:
            if anexo_obj.arquivo:
                filename = os.path.basename(anexo_obj.arquivo.name)
                anexos_para_email_context.append({'descricao': anexo_obj.descricao, 'nome_arquivo': filename})
            else:
                anexos_para_email_context.append({'descricao': anexo_obj.descricao, 'nome_arquivo': 'N/A'})

        email_context = {
            'cadastro': cadastro,
            'liberar_url': liberar_url,
            'bloquear_url': bloquear_url,
            'anexos_info': anexos_para_email_context, # Passa a nova lista com nome e descrição
        }

        email_html_content = render_to_string('email_financeiro.html', email_context)

        #to_email_list = ['cobranca@lautbeer.com.br']
        to_email_list = ['lorrane.ramos@lautbeer.com.br']

        #if request.user.is_authenticated and request.user.email:
        #    to_email_list.append(request.user.email)

        #bcc_email_list = ['lorrane.ramos@lautbeer.com.br']

        from_email = settings.DEFAULT_FROM_EMAIL
        subject = f'Cadastro Pendente de Liberação: {cadastro.razao_social}'

        email = EmailMessage(
            subject,
            email_html_content,
            from_email,
            to_email_list,
            #bcc=bcc_email_list
        )
        email.content_subtype = "html"
        
        for anexo_obj in anexos_db:
            try:
                if anexo_obj.arquivo and os.path.exists(anexo_obj.arquivo.path):
                    with open(anexo_obj.arquivo.path, 'rb') as f:
                        filename = os.path.basename(anexo_obj.arquivo.name)
                        
                        content_type = None
                        if hasattr(anexo_obj.arquivo, 'file') and hasattr(anexo_obj.arquivo.file, 'content_type'):
                            content_type = anexo_obj.arquivo.file.content_type
                        elif hasattr(anexo_obj.arquivo, 'content_type'):
                            content_type = anexo_obj.arquivo.content_type
                        else:
                            content_type, _ = mimetypes.guess_type(filename)
                        
                        if not content_type:
                            content_type = 'application/octet-stream'

                        email.attach(filename, f.read(), content_type)
                else:
                    print(f"ATENÇÃO: Arquivo físico não encontrado ou anexo.arquivo é None para {anexo_obj.descricao}. Caminho: {anexo_obj.arquivo.path if anexo_obj.arquivo else 'N/A'}")
            except FileNotFoundError:
                print(f"ATENÇÃO: Arquivo de anexo não encontrado no caminho: {anexo_obj.arquivo.path}")
            except Exception as e:
                print(f"ERRO: Falha ao anexar arquivo {anexo_obj.arquivo.name}: {e}")

        try:
            email.send()
        except Exception as e:
            print(f"ERRO: Falha ao enviar e-mail de 'pendente_financeiro': {e}")
            messages.error(request, "Erro ao enviar e-mail de notificação financeira. Verifique os logs.")

        messages.success(request, f"O cadastro de '{cadastro.razao_social}' foi aprovado para análise financeira!")
        return render(request, 'cadastro_ja_processado.html', {'cadastro': cadastro})

    else:
        messages.error(request, "Ação inválida. Use o formulário de aprovação.")
        return render(request, 'cadastro_ja_processado.html', {'cadastro': cadastro})

@require_http_methods(["GET", "POST"])
def cadastro_rejeitar(request, cadastro_id):
    cadastro = get_object_or_404(Cadastro, id=cadastro_id)

    if cadastro.status not in ['pendente', 'cadastrado']:
        context = {'cadastro': cadastro}
        messages.info(request, f"O cadastro de '{cadastro.razao_social}' já foi processado e não pode ser rejeitado novamente.")
        return render(request, 'cadastro_ja_processado.html', context)

    if request.method == 'GET':
        action_url = reverse('salesapp:cadastro_rejeitar', args=[cadastro.id])
        return render(request, 'cadastro_rejeitar.html', {'cadastro': cadastro, 'erro_motivo': False, 'action_url': action_url})
        
    elif request.method == 'POST':
        motivo = request.POST.get('motivo_rejeicao', '').strip()
        if not motivo:
            messages.error(request, "O motivo da rejeição não pode estar vazio.")
            action_url = reverse('salesapp:cadastro_rejeitar', args=[cadastro.id])
            return render(request, 'cadastro_rejeitar.html', {'cadastro': cadastro, 'erro_motivo': True, 'action_url': action_url})

        cadastro.status = 'rejeitado'
        cadastro.motivo_rejeicao = motivo
        cadastro.save()

        anexos_db = AnexoCadastro.objects.filter(cadastro=cadastro)

        anexos_para_email_context = []
        for anexo_obj in anexos_db:
            if anexo_obj.arquivo:
                filename = os.path.basename(anexo_obj.arquivo.name)
                anexos_para_email_context.append({'descricao': anexo_obj.descricao, 'nome_arquivo': filename})
            else:
                anexos_para_email_context.append({'descricao': anexo_obj.descricao, 'nome_arquivo': 'N/A'})

        email_context = {
            'cadastro': cadastro,
            'motivo': motivo,
            'rejeitor_email': request.user.email if request.user.is_authenticated else "rejeitor_desconhecido",
            'anexos_info': anexos_para_email_context, # Passa a nova lista com nome e descrição
        }
        email_html_content = render_to_string('cadastro_rejeitado.html', email_context) 

        #to_email_list = ['cadastroclientes@lautbeer.com.br']
        to_email_list = ['lorrane.ramos@lautbeer.com.br']

        #if request.user.is_authenticated and request.user.email:
        #    to_email_list.append(request.user.email)

        #bcc_email_list = ['lorrane.ramos@lautbeer.com.br']

        from_email = settings.DEFAULT_FROM_EMAIL
        subject = f'Cliente não cadastrado: {cadastro.razao_social}'

        email = EmailMessage(
            subject,
            email_html_content,
            from_email,
            to_email_list,
        #   bcc_email_list
        )
        email.content_subtype = "html"
        
        try:
            email.send()
        except Exception as e:
            print(f"ERRO: Falha ao enviar e-mail de 'rejeitado_cadastro': {e}")
            messages.error(request, "Erro ao enviar e-mail de notificação de rejeição. Verifique os logs.")

        messages.success(request, f"Cadastro de {cadastro.razao_social} rejeitado na etapa de cadastro. Motivo: {motivo}")
        return render(request, 'cadastro_ja_processado.html', {'cadastro': cadastro})
    else:
        messages.error(request, "Ação inválida.")
        return render(request, 'cadastro_ja_processado.html', {'cadastro': cadastro})
    
@require_http_methods(["GET", "POST"])
def liberar_cadastro(request, cadastro_id):
    cadastro = get_object_or_404(Cadastro, id=cadastro_id)

    if cadastro.status != 'cadastrado': 
        context = {'cadastro': cadastro}
        messages.info(request, f"O cadastro de '{cadastro.razao_social}' já foi processado financeiramente e não pode ser liberado novamente.")
        return render(request, 'cadastro_ja_processado.html', context)

    if request.method == 'GET':
        action_url = reverse('salesapp:liberar_cadastro', args=[cadastro.id])
        return render(request, 'cadastro_confirmar.html', {'cadastro': cadastro, 'action_url': action_url})

    elif request.method == 'POST':
        cadastro.status = 'liberado' 
        cadastro.save()

        anexos_db = AnexoCadastro.objects.filter(cadastro=cadastro)

        anexos_para_email_context = []
        for anexo_obj in anexos_db:
            if anexo_obj.arquivo:
                filename = os.path.basename(anexo_obj.arquivo.name)
                anexos_para_email_context.append({'descricao': anexo_obj.descricao, 'nome_arquivo': filename})
            else:
                anexos_para_email_context.append({'descricao': anexo_obj.descricao, 'nome_arquivo': 'N/A'})


        email_context = {
            'cadastro': cadastro,
            'aprovador_email': request.user.email if request.user.is_authenticated else "aprovador_desconhecido",
            'anexos_info': anexos_para_email_context, # Passa a nova lista com nome e descrição
        }
        email_html_content = render_to_string('cadastro_aprovado.html', email_context)

        #to_email_list = ['cadastroclientes@lautbeer.com.br', 'cobranca@lautbeer.com.br']
        to_email_list = ['lorrane.ramos@lautbeer.com.br']

        #if request.user.is_authenticated and request.user.email:
        #    to_email_list.append(request.user.email)

        #bcc_email_list = ['lorrane.ramos@lautbeer.com.br']

        from_email = settings.DEFAULT_FROM_EMAIL
        subject = f'Cliente cadastrado: {cadastro.razao_social}'

        email = EmailMessage(
            subject,
            email_html_content,
            from_email,
            to_email_list,
            #bcc_email_list
        )

        email.content_subtype = "html"
        
        try:
            email.send()
        except Exception as e:
            print(f"ERRO: Falha ao enviar e-mail de 'liberado_cadastro': {e}")
            messages.error(request, "Erro ao enviar e-mail de liberação de cadastro. Verifique os logs.")

        messages.success(request, f"O cadastro de '{cadastro.razao_social}' foi liberado para faturamento.")
        return render(request, 'cadastro_ja_processado.html', {'cadastro': cadastro})

    else:
        messages.error(request, "Ação inválida.")
        return render(request, 'cadastro_ja_processado.html', {'cadastro': cadastro})

@require_http_methods(["GET", "POST"])
def bloquear_cadastro(request, cadastro_id):
    cadastro = get_object_or_404(Cadastro, id=cadastro_id)

    if cadastro.status != 'cadastrado': 
        context = {'cadastro': cadastro}
        messages.info(request, f"O cadastro de '{cadastro.razao_social}' já foi processado financeiramente e não pode ser bloqueado novamente.")
        return render(request, 'cadastro_ja_processado.html', context)

    if request.method == 'GET':
        action_url = reverse('salesapp:bloquear_cadastro', args=[cadastro.id])
        return render(request, 'cadastro_rejeitar.html', {'cadastro': cadastro, 'erro_motivo': False, 'action_url': action_url})

    elif request.method == 'POST':
        motivo = request.POST.get('motivo_rejeicao', '').strip()
        if not motivo:
            messages.error(request, "O motivo da rejeição não pode estar vazio.")
            action_url = reverse('salesapp:bloquear_cadastro', args=[cadastro.id])
            return render(request, 'cadastro_rejeitar.html', {'cadastro': cadastro, 'erro_motivo': True, 'action_url': action_url})

        cadastro.status = 'rejeitado'
        cadastro.motivo_rejeicao = motivo
        cadastro.save()

        anexos_db = AnexoCadastro.objects.filter(cadastro=cadastro)

        anexos_para_email_context = []
        for anexo_obj in anexos_db:
            if anexo_obj.arquivo:
                filename = os.path.basename(anexo_obj.arquivo.name)
                anexos_para_email_context.append({'descricao': anexo_obj.descricao, 'nome_arquivo': filename})
            else:
                anexos_para_email_context.append({'descricao': anexo_obj.descricao, 'nome_arquivo': 'N/A'})

        email_context = {
            'cadastro': cadastro,
            'motivo': motivo,
            'rejeitor_email': request.user.email if request.user.is_authenticated else "rejeitor_desconhecido",
            'anexos_info': anexos_para_email_context, # Passa a nova lista com nome e descrição
        }
        email_html_content = render_to_string('cadastro_rejeitado.html', email_context) 

        #to_email_list = ['cadastroclientes@lautbeer.com.br', 'cobranca@lautbeer.com.br']
        to_email_list = ['lorrane.ramos@lautbeer.com.br']

        #if request.user.is_authenticated and request.user.email:
        #    to_email_list.append(request.user.email)

        #bcc_email_list = ['lorrane.ramos@lautbeer.com.br']

        from_email = settings.DEFAULT_FROM_EMAIL
        subject = f'Cliente não cadastrado: {cadastro.razao_social}'

        email = EmailMessage(
            subject,
            email_html_content,
            from_email,
            to_email_list,
        #    bcc_email_list
        )
        
        email.content_subtype = "html"
        
        try:
            email.send()
        except Exception as e:
            print(f"ERRO: Falha ao enviar e-mail de 'bloquear_cadastro': {e}")
            messages.error(request, "Erro ao enviar e-mail de bloqueio de cadastro. Verifique os logs.")

        messages.success(request, f"O cadastro de {cadastro.razao_social} rejeitado pelo financeiro. Motivo: {motivo}")
        return render(request, 'cadastro_ja_processado.html', {'cadastro': cadastro})
    else:
        messages.error(request, "Ação inválida.")
        return render(request, 'cadastro_ja_processado.html', {'cadastro': cadastro})
    
def user_login(request):
    if request.method == 'POST':
        form = LoginForm(request=request, data=request.POST)

        print("Requisição POST recebida para login.")
        print(f"Dados do formulário: {request.POST}")

        if form.is_valid():
            user = form.get_user()
            print(f"Formulário válido. Usuário autenticado: {user.username}")

            # Loga o usuário
            login(request, user)
            print(f"Usuário {user.username} logado com sucesso.")

            return redirect('salesapp:inicio')

        else:
            print("Formulário inválido.")
            print(f"Erros do formulário: {form.errors.as_data()}")
            for field, errors in form.errors.items():
                print(f"Campo '{field}': {errors}")
            print(f"Erros gerais (non_field_errors): {form.non_field_errors()}")

    else:
        form = LoginForm(request=request)
        print("Requisição GET recebida para formulário de login.")

    return render(request, 'login.html', {'form': form})

def user_logout(request):

    logout(request)
    messages.success(request, "Você foi desconectado com sucesso.")
    return redirect('salesapp:login')
    html_email_template_name = 'registration/password_reset_email.html'

class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    def form_valid(self, form):
        response = super().form_valid(form)
        return response
    
class CustomPasswordResetView(auth_views.PasswordResetView):
    html_email_template_name = 'registration/password_reset_email.html'

    def post(self, request, *args, **kwargs):
        print(">>> DEBUG: Método POST da CustomPasswordResetView chamado.")
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        print(">>> DEBUG: Método form_valid da CustomPasswordResetView chamado. Início do envio do e-mail.")
        response = super().form_valid(form)
        print(">>> DEBUG: Método form_valid da CustomPasswordResetView concluído. E-mail supostamente enviado.")
        return response
    
@login_required
def bonificacoes(request):
    context = {
        'user': request.user,
    }
    return render(request, 'bonificacoes.html', context)

@login_required
def nova_bonificacao(request):
    return render(request, 'nova_bonificacao.html')