import re
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
    """
    Pedido de chopp para retirada. O mesmo registro vai do pedido ao faturamento:
    PENDENTE (vendedor gravou, sem dia) -> AGENDADO (backoffice definiu dia e hora)
    -> ENVIADO (dia confirmado) -> ENTREGUE (fábrica marcou) -> FINALIZADO (Faturamento);
    CANCELADO em qualquer ponto antes de finalizar.
    """

    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('AGENDADO', 'Agendado'),
        ('ENVIADO', 'Enviado'),
        ('ENTREGUE', 'Entregue'),
        ('FINALIZADO', 'Finalizado'),
        ('CANCELADO', 'Cancelado'),
    ]

    vendedor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='pedidos_chopp')
    data_solicitacao = models.DateTimeField(auto_now_add=True, db_index=True)

    cliente_codigo = models.CharField(max_length=15)
    cliente_loja = models.CharField(max_length=4)
    cliente_razao_social = models.CharField(max_length=100)
    cliente_nome_fantasia = models.CharField(max_length=100, blank=True)
    cliente_cpf_cnpj = models.CharField(max_length=18)

    # Retirada: o backoffice define dia e hora (vazios enquanto PENDENTE)
    data_retirada = models.DateField(null=True, blank=True, db_index=True)
    hora_retirada = models.TimeField(null=True, blank=True)
    agendado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_chopp_agendados')
    agendado_em = models.DateTimeField(null=True, blank=True)

    # Vêm do cadastro do cliente no Protheus (CIEC 01, filial 0101); ninguém altera
    condicao_pagamento = models.CharField(max_length=10)
    condicao_pagamento_descricao = models.CharField(max_length=60)
    tabela_preco = models.CharField(max_length=10, blank=True)

    observacao = models.TextField(blank=True)
    # Justificativa do Faturamento para o que alterou (o vendedor não edita)
    observacao_faturamento = models.TextField(blank=True)

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDENTE', db_index=True)
    pedido_protheus = models.CharField(max_length=20, blank=True)

    # Fábrica: marca a retirada (ENTREGUE) ou "não retirou"
    entregue_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_chopp_entregues')
    entregue_em = models.DateTimeField(null=True, blank=True)

    alterado_pelo_faturamento = models.BooleanField(default=False)
    usuario_faturamento = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_chopp_processados')
    data_finalizacao = models.DateTimeField(null=True, blank=True)
    motivo_cancelamento = models.TextField(blank=True)
    cancelado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_chopp_cancelados')
    data_cancelamento = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Agendamento de Chopp"
        verbose_name_plural = "Agendamentos de Chopp"
        ordering = ['data_retirada', 'hora_retirada', 'id']

    def __str__(self):
        return f"Chopp #{self.id} - {self.cliente_razao_social}"

    @property
    def cliente_nome(self):
        return self.cliente_nome_fantasia or self.cliente_razao_social

    @property
    def horario(self):
        """Ex.: '10:30' (hora livre definida pelo backoffice); vazio enquanto pendente."""
        return self.hora_retirada.strftime('%H:%M') if self.hora_retirada else ''

    @property
    def faixa_horario(self):
        return self.horario

    @property
    def litros(self):
        """Litragem do pedido (barris: litros pelo nome do produto, ex. '30L')."""
        return sum(i.litros for i in self.itens.all())

    @property
    def total(self):
        return sum((item.valor_total for item in self.itens.all()), 0)

    @property
    def total_solicitado(self):
        return sum((item.preco_solicitado * item.qtd_solicitada for item in self.itens.all() if item.qtd_solicitada), 0)

    def tem_alteracao_do_faturamento(self):
        """O pedido final é diferente do que o vendedor agendou?"""
        return any(i.situacao != 'MANTIDO' for i in self.itens.all())


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
    # Preço veio da tabela do cliente no Protheus (travado para o vendedor)
    preco_da_tabela = models.BooleanField(default=False)
    # Quem incluiu o item depois do pedido (vazio = veio no pedido)
    ORIGEM_CHOICES = [('', 'Pedido'), ('FABRICA', 'Fábrica'), ('FATURAMENTO', 'Faturamento')]
    incluido_por = models.CharField(max_length=12, choices=ORIGEM_CHOICES, blank=True, default='')

    def save(self, *args, **kwargs):
        self.valor_total = self.preco_unitario * self.quantidade
        super().save(*args, **kwargs)

    @property
    def litros_por_unidade(self):
        """Litros do barril pelo nome do produto ('BARRIL CHOPP PILSEN 30L' -> 30); copos e outros = 0."""
        achado = re.search(r'(\d+)\s*L\b', self.produto_descricao.upper())
        return int(achado.group(1)) if achado else 0

    @property
    def litros(self):
        return 0 if self.removido else self.quantidade * self.litros_por_unidade

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
        if self.situacao == 'INCLUIDO':
            return 'Incluído pela Fábrica' if self.incluido_por == 'FABRICA' else 'Incluído pelo Faturamento'
        return {
            'REMOVIDO': 'Removido na retirada/faturamento',
            'ALTERADO': 'Alterado na retirada/faturamento',
            'MANTIDO': 'Mantido',
        }[self.situacao]

    @property
    def foi_alterado(self):
        return self.situacao != 'MANTIDO'


class DiaConfirmadoChopp(models.Model):
    """Dia de retirada confirmado pela Gestão Comercial: os agendamentos foram enviados e o dia fica travado."""
    data = models.DateField(unique=True)
    confirmado_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name='dias_chopp_confirmados')
    confirmado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Dia de retirada confirmado"
        verbose_name_plural = "Dias de retirada confirmados"
        ordering = ['-data']

    def __str__(self):
        return f"{self.data:%d/%m/%Y} confirmado por {self.confirmado_por}"
