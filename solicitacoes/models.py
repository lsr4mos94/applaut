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


class Bonificacao(models.Model):
    TIPOS_CHOICES = [
        ('VERBA_VENDEDOR', 'Verba Vendedor'),
        ('ACORDO_COMERCIAL', 'Acordo Comercial'),
        ('NEGOCIACAO_ESPECIAL', 'Negociação Especial'),
        ('SAC', 'SAC'),
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
        return self.tipo == 'NEGOCIACAO_ESPECIAL' and self.status == 'PENDENTE'
    
    @property
    def pode_aprovar(self):
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

    def save(self, *args, **kwargs):
        self.valor_total = self.preco_tabela * self.quantidade
        super().save(*args, **kwargs)