from django.db import models
from django.contrib.auth.models import User

class SolicitacaoVerba(models.Model):
    CATEGORIAS_CHOICES = [
        ('CONFRATERNIZACAO', 'Confraternização'),
        ('DESPESA_VIAGEM', 'Despesas de Viagem'),
        ('DESPESA_ECOMMERCE', 'Despesas Ecommerce'),
        ('EVENTOS', 'Eventos'),
        ('FRETE', 'Frete'),
        ('LOCACAO_EQUIPAMENTOS', 'Locação de Equipamentos'),
        ('MANUTENCAO_INDUSTRIAL', 'Manutenção e Conservação'),
        ('MANUTENCAO_EQUIPAMENTO', 'Manutenção de Equipamentos'),
        ('MANUTENCAO_VEICULOS', 'Manutenção de Veículos'),
        ('MARKETING', 'Marketing'),
        ('PLANTAO', 'Plantão'),
        ('SERVICO_TERCEIRO', 'Serviço de Terceiros'),
    ]

    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('APROVADO', 'Aprovado'),
        ('REPROVADO', 'Reprovado'),
        ('CONCLUIDO', 'Concluído'),
    ]

    FORMA_PAGAMENTO_CHOICES = [
        ('BOLETO', 'Boleto'),
        ('DINHEIRO', 'Dinheiro'),
        ('PIX', 'PIX'),
        ('TRANSFERENCIA', 'Transferência'),
    ]

    TIPO_FORNECEDOR_CHOICES = [
        ('EXISTENTE', 'Cadastrado no Protheus'),
        ('NOVO', 'Novo Fornecedor / Sem Cadastro'),
    ]

    tipo_fornecedor = models.CharField(max_length=10, choices=TIPO_FORNECEDOR_CHOICES, default='EXISTENTE')

    fornecedor_codigo = models.CharField("Código Protheus", max_length=8, blank=True, null=True)
    fornecedor_loja = models.CharField("Loja Protheus", max_length=4, blank=True, null=True)

    fornecedor_nome_razao = models.CharField("Razão Social / Nome", max_length=255)
    fornecedor_cpf_cnpj = models.CharField("CPF/CNPJ", max_length=18)

    produto_servico = models.CharField("Produto ou Serviço", max_length=255)
    categoria = models.CharField(max_length=50, choices=CATEGORIAS_CHOICES)
    valor = models.DecimalField(max_digits=12, decimal_places=2)
    data_vencimento = models.DateField()
    forma_pagamento = models.CharField(max_length=50, choices=FORMA_PAGAMENTO_CHOICES)
    observacoes = models.TextField("Observações", blank=True)

    tem_documento = models.BooleanField("Possui Nota/Comprovante?", default=False)
    arquivo_nota = models.FileField(
        "Arquivo da Nota Fiscal", 
        upload_to='solicitacoes/verba/notas/%Y/%m/', 
        blank=True, 
        null=True
    )
    arquivo_boleto = models.FileField(
        "Arquivo do Boleto", 
        upload_to='solicitacoes/verba/boletos/%Y/%m/', 
        blank=True, 
        null=True
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    usuario_solicitante = models.ForeignKey(User, on_delete=models.PROTECT, related_name='solicitacoes_criadas')
    data_solicitacao = models.DateTimeField(auto_now_add=True)
    
    usuario_aprovador = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='solicitacoes_aprovadas')
    data_aprovacao = models.DateTimeField(null=True, blank=True)
    obs_aprovacao = models.TextField("Observações da Aprovação/Reprovação", blank=True, null=True)

    num_titulo = models.CharField(max_length=9, blank=True, null=True, verbose_name="Número do Título Protheus")

    class Meta:
        verbose_name = "Solicitação de Verba"
        verbose_name_plural = "Solicitações de Verba"
        ordering = ['-data_solicitacao']

    def __str__(self):
        return f"{self.id} - {self.fornecedor_nome_razao} (R$ {self.valor})"