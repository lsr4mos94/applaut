from django.db import models
from django.contrib.auth.models import User

TIPO_PLANTAO = [('TECNICO', 'PLANTÃO TÉCNICO'), ('REPOSICAO', 'PLANTÃO DE REPOSIÇÃO')]
OCORRENCIAS = [
    ('CHOPEIRA', 'CHOPEIRA'), ('MANOMETRO', 'MANÔMETRO'), ('CILINDRO', 'CILINDRO'),
    ('EXTRATORA', 'EXTRATORA'), ('TROCA_BARRIL', 'TROCA DE BARRIL'),
    ('ENTREGA_BARRIL', 'ENTREGA DE BARRIL'), ('OUTRO', 'OUTRO')
]
STATUS_CHOICES = [
    ('PENDENTE', 'Pendente'),
    ('CONFIRMADO', 'Confirmado'),
    ('RECUSADO', 'Recusado'),
]

class Plantao(models.Model):
    codigo_cliente = models.CharField(max_length=20)
    loja_cliente = models.CharField(max_length=50)
    nome_cliente = models.CharField(max_length=100)
    cep = models.CharField(max_length=9)
    estado = models.CharField(max_length=2)
    cidade = models.CharField(max_length=100)
    bairro = models.CharField(max_length=100)
    endereco = models.CharField(max_length=255)
    numero = models.CharField(max_length=20)
    complemento = models.CharField(max_length=100, blank=True, null=True)
    vendedor = models.ForeignKey(User, on_delete=models.CASCADE)
    tipo = models.CharField(max_length=20, choices=TIPO_PLANTAO)
    ocorrencia = models.CharField(max_length=50, choices=OCORRENCIAS)
    ocorrencia_outro = models.CharField(max_length=255, blank=True, null=True)
    observacoes = models.TextField(blank=True)
    taxa = models.BooleanField(default=False)
    valor_taxa = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    horario = models.TimeField()
    data_solicitacao = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    zenvia_message_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)

class Bonificacao(models.Model):
    TIPOS_CHOICES = [
        ('VERBA_VENDEDOR', 'Verba Vendedor'),
        ('ACORDO_COMERCIAL', 'Acordo Comercial'),
        ('NEGOCIACAO_ESPECIAL', 'Negociação Especial'),
        ('SAC', 'SAC'),
        ('ATIVACAO_MARCA', "Ativação de Marca"),
        ('MARKETING', "Marketing")
    ]

    PLATAFORMA_CHOICES = [
        ('CIEC', 'CIEC'),
        ('ISLA', 'ISLA'),
        ('WRP', 'WRP'),
    ]

    METODO_CHOICES = [
        ('ENTREGA', 'Entrega'),
        ('RETIRADA', 'Retirada'),
    ]

    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('APROVADO', 'Aprovado'),
        ('REPROVADO', 'Reprovado'),
        ('CONCLUIDO', 'Concluído'),
    ]

    tipo = models.CharField(max_length=20, choices=TIPOS_CHOICES)
    vendedor = models.ForeignKey(User, on_delete=models.PROTECT)
    data_solicitacao = models.DateTimeField(auto_now_add=True)
    
    cliente_codigo = models.CharField(max_length=15)
    cliente_loja = models.CharField(max_length=4)
    cliente_razao_social = models.CharField(max_length=100)
    cliente_nome_fantasia = models.CharField(max_length=100)
    cliente_cpf_cnpj = models.CharField(max_length=18)
    cliente_grupo = models.CharField(max_length=50, blank=True, null=True)
    
    justificativa = models.TextField(verbose_name="Observação/Justificativa")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDENTE')

    data_aprovacao = models.DateTimeField(null=True, blank=True)
    usuario_aprovador = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='aprovacoes')
    observacao_reprovacao = models.TextField(null=True, blank=True)

    pedido_protheus = models.CharField(max_length=20, blank=True, null=True)

    plataforma = models.CharField(max_length=10, choices=PLATAFORMA_CHOICES, null=True, blank=True)
    metodo_entrega = models.CharField(max_length=10, choices=METODO_CHOICES, null=True, blank=True)
    data_entrega_retirada = models.DateField(null=True, blank=True)
    foto_sac = models.ImageField(upload_to='bonificacoes/sac/', null=True, blank=True)

    def get_total(self):
        return sum(item.valor_total for item in self.itens.all())
    
    @property
    def pode_aprovar(self):
        # Retorna Verdadeiro se for Negociação Especial ou SAC, e estiver PENDENTE
        return self.tipo in ['NEGOCIACAO_ESPECIAL', 'SAC'] and self.status == 'PENDENTE'

    class Meta:
        verbose_name = "Bonificação"
        verbose_name_plural = "Bonificações"

    def __str__(self):
        return f"Bonif. {self.id} - {self.cliente_razao_social}"

class BonificacaoItem(models.Model):
    bonificacao = models.ForeignKey(Bonificacao, related_name='itens', on_delete=models.CASCADE)
    
    produto_codigo = models.CharField(max_length=15)
    produto_descricao = models.CharField(max_length=100)
    
    preco_tabela = models.DecimalField(max_digits=12, decimal_places=2)
    quantidade = models.IntegerField()
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)

    acordo_vinculado = models.ForeignKey(
        'cadastros.AcordoComercial',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='utilizacoes_diretas'
    )

    def save(self, *args, **kwargs):
        self.valor_total = self.preco_tabela * self.quantidade
        super().save(*args, **kwargs)

class FotoBonificacao(models.Model):
    bonificacao = models.ForeignKey(Bonificacao, on_delete=models.CASCADE, related_name='fotos')
    arquivo = models.ImageField(upload_to='sac/')
    data_upload = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Foto #{self.id} - Bonificação {self.bonificacao.id}"


class SolicitacaoChopp(models.Model):
    """Pedido de chopp lançado pelo vendedor e processado pelo Faturamento (sem aprovação)."""

    RECEBIMENTO_CHOICES = [
        ('RETIRADA_FABRICA', 'Retirada na Fábrica'),
        ('RETIRADA_LOGISTICA', 'Retirada na Logística'),
        ('ENTREGA', 'Entrega'),
    ]
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('FINALIZADO', 'Finalizado'),
        ('CANCELADO', 'Cancelado'),
    ]
    PRAZO_CHOICES = [
        ('A VISTA', 'A VISTA'),
        ('7 DIAS', '7 DIAS'),
        ('14 DIAS', '14 DIAS'),
        ('21 DIAS', '21 DIAS'),
        ('28 DIAS', '28 DIAS'),
    ]

    vendedor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='pedidos_chopp')
    data_solicitacao = models.DateTimeField(auto_now_add=True, db_index=True)

    cliente_codigo = models.CharField(max_length=15)
    cliente_loja = models.CharField(max_length=4)
    cliente_razao_social = models.CharField(max_length=100)
    cliente_nome_fantasia = models.CharField(max_length=100, blank=True)
    cliente_cpf_cnpj = models.CharField(max_length=18)

    recebimento = models.CharField(max_length=20, choices=RECEBIMENTO_CHOICES)
    data_entrega = models.DateField(null=True, blank=True)
    prazo_pagamento = models.CharField(max_length=100, choices=PRAZO_CHOICES)
    # Prazo que o vendedor escolheu (o Faturamento pode trocar o prazo_pagamento)
    prazo_pagamento_solicitado = models.CharField(max_length=100, choices=PRAZO_CHOICES, blank=True)
    observacao = models.TextField(blank=True)
    # Justificativa do Faturamento para o que alterou (o vendedor não edita)
    observacao_faturamento = models.TextField(blank=True)

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDENTE', db_index=True)
    pedido_protheus = models.CharField(max_length=20, blank=True)

    alterado_pelo_faturamento = models.BooleanField(default=False)
    usuario_faturamento = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_chopp_processados')
    data_finalizacao = models.DateTimeField(null=True, blank=True)
    motivo_cancelamento = models.TextField(blank=True)
    cancelado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_chopp_cancelados')
    data_cancelamento = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Solicitação de Chopp"
        verbose_name_plural = "Solicitações de Chopp"
        ordering = ['-data_solicitacao']

    def __str__(self):
        return f"Chopp #{self.id} - {self.cliente_razao_social}"

    @property
    def total(self):
        return sum((item.valor_total for item in self.itens.all()), 0)

    @property
    def total_solicitado(self):
        return sum((item.preco_solicitado * item.qtd_solicitada for item in self.itens.all() if item.qtd_solicitada), 0)

    @property
    def prazo_foi_alterado(self):
        return bool(self.prazo_pagamento_solicitado) and self.prazo_pagamento_solicitado != self.prazo_pagamento

    def tem_alteracao_do_faturamento(self):
        """O pedido final é diferente do que o vendedor lançou?"""
        return self.prazo_foi_alterado or any(i.situacao != 'MANTIDO' for i in self.itens.all())


class SolicitacaoChoppItem(models.Model):
    solicitacao = models.ForeignKey(SolicitacaoChopp, related_name='itens', on_delete=models.CASCADE)
    produto_codigo = models.CharField(max_length=15)
    produto_descricao = models.CharField(max_length=100)

    # Valores atuais (o Faturamento pode corrigir)
    quantidade = models.IntegerField()
    preco_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)

    # Valores que o vendedor lançou (para comparar depois); vazios em item incluído pelo Faturamento
    qtd_solicitada = models.IntegerField(null=True, blank=True)
    preco_solicitado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Item que o vendedor pediu e o Faturamento tirou: fica com quantidade 0 para o histórico
    removido = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        self.valor_total = self.preco_unitario * self.quantidade
        super().save(*args, **kwargs)

    @property
    def situacao(self):
        if self.removido:
            return 'REMOVIDO'
        if self.qtd_solicitada is None:
            return 'INCLUIDO'
        if self.qtd_solicitada != self.quantidade or self.preco_solicitado != self.preco_unitario:
            return 'ALTERADO'
        return 'MANTIDO'

    @property
    def situacao_display(self):
        return {
            'REMOVIDO': 'Removido pelo Faturamento',
            'INCLUIDO': 'Incluído pelo Faturamento',
            'ALTERADO': 'Alterado pelo Faturamento',
            'MANTIDO': 'Mantido',
        }[self.situacao]

    @property
    def foi_alterado(self):
        return self.situacao != 'MANTIDO'

