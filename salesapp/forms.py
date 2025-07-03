from django import forms
from .models import Cadastro
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm

class NovoCadastroForm(forms.ModelForm):
    class Meta:
        model = Cadastro
        exclude = ['vendedor', 'status', 'motivo_rejeicao', 'data_cadastro', 'data_atualizacao']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            'plataforma': 'Plataforma',
            'tipo_cliente': 'Tipo de Cliente',
            'razao_social': 'Razão Social',
            'cgc': 'CGC',
            'inscricao_estadual': 'Inscrição Estadual (opcional)',
            'email': 'Email',
            'telefone': 'Telefone',
            'cep': 'CEP',
            'estado': 'Estado (Ex: SP)',
            'cidade': 'Cidade',
            'bairro': 'Bairro',
            'endereco': 'Endereço',
            'numero': 'Número',
            'complemento': 'Complemento (opcional)',
            'grupo_cliente': 'Grupo Cliente',
            'condicao_pagamento': 'Condição de Pagamento',
            'horario_entrega': 'Horário de Entrega',
            'nome_socio': 'Nome do Sócio (opcional)',
            'cpf_socio': 'CPF do Sócio (opcional)',
            'cep_socio': 'CEP do Sócio (opcional)',
            'estado_socio': 'Estado do Sócio (opcional)',
            'cidade_socio': 'Cidade do Sócio (opcional)',
            'bairro_socio': 'Bairro do Sócio (opcional)',
            'endereco_socio': 'Endereço do Sócio (opcional)',
            'numero_socio': 'Número do Sócio (opcional)',
            'complemento_socio': 'Complemento do Sócio (opcional)',
            'nome_financeiro': 'Nome Financeiro (opcional)',
            'telefone_financeiro': 'Telefone Financeiro (opcional)',
            'nome_compras': 'Nome Compras (opcional)',
            'telefone_compras': 'Telefone Compras (opcional)',
        }

        for field_name, placeholder_text in placeholders.items():
            if field_name in self.fields:
                self.fields[field_name].widget.attrs['placeholder'] = placeholder_text
                self.fields[field_name].widget.attrs['class'] = 'form-input'
                

class LoginForm(AuthenticationForm):

    username = forms.CharField(
        label="Nome de Usuário",
        max_length=150,
        widget=forms.TextInput(attrs={'placeholder': 'Nome de Usuário'})
    )
    password = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(attrs={'placeholder': 'Senha'})
    )