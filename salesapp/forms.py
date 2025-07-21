from django import forms
from .models import Cadastro, Bonificacao, ItemBonificacao
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

class BonificacaoForm(forms.ModelForm):
    class Meta:
        model = Bonificacao
        fields = [
            'tipo_bonificacao',
            'cod_cliente',
            'loja_cliente',
            'razao_social',
            'nome_fantasia',
            'cgc',
            'grupo_cliente',
            'motivo',
        ]
        widgets = {
            'tipo_bonificacao': forms.RadioSelect(choices=Bonificacao.TIPO_BONIFICACAO_CHOICES),
        }
        labels = {
            'tipo_bonificacao': 'Tipo de Bonificação',
            'cod_cliente': 'Código Cliente',
            'loja_cliente': 'Loja Cliente',
            'razao_social': 'Razão Social',
            'nome_fantasia': 'Nome Fantasia',
            'cgc': 'CGC',
            'grupo_cliente': 'Grupo Cliente',
            'motivo': 'Motivo',
            'observacoes': 'Observações',
        }


class ItemBonificacaoForm(forms.ModelForm):
    class Meta:
        model = ItemBonificacao
        fields = [
            'cod_produto',
            'desc_produto',
            'preco_tabela',
            'quantidade',
        ]
        widgets = {
            'preco_tabela': forms.NumberInput(attrs={'step': '0.01'}),
            'quantidade': forms.NumberInput(attrs={'min': '1'}),
        }
        labels = {
            'cod_produto': 'Código do Produto',
            'desc_produto': 'Descrição do Produto',
            'preco_tabela': 'Preço de Tabela',
            'quantidade': 'Quantidade',
        }

ItemBonificacaoFormSet = forms.inlineformset_factory(
    Bonificacao,
    ItemBonificacao,
    form=ItemBonificacaoForm,
    extra=0,
    can_delete=True,
    min_num=1,
    validate_min=True
)