from django import forms
from .models import SolicitacaoVerba

class SolicitacaoVerbaForm(forms.ModelForm):
    class Meta:
        model = SolicitacaoVerba
        fields = [
            'fornecedor_nome_razao', 
            'fornecedor_cpf_cnpj', 
            'categoria', 
            'produto_servico', 
            'valor', 
            'data_vencimento',
            'forma_pagamento', 
            'observacoes'
        ]
        
        widgets = {
            'fornecedor_nome_razao': forms.TextInput(attrs={'class': 'form-control'}),
            'fornecedor_cpf_cnpj': forms.TextInput(attrs={'class': 'form-control mask-cpf-cnpj'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'produto_servico': forms.TextInput(attrs={'class': 'form-control'}),
            'valor': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'data_vencimento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'forma_pagamento': forms.Select(attrs={'class': 'form-select'}),
            'observacoes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }