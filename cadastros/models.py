from django.db import models
from django.contrib.auth.models import User
from solicitacoes.models import Bonificacao

class VerbaMensal(models.Model):
    MESES_CHOICES = [
        (1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'),
        (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'),
        (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro'),
    ]

    vendedor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='verbas')
    mes_referencia = models.IntegerField(choices=MESES_CHOICES, verbose_name="Mês de Referência")
    ano_referencia = models.IntegerField(verbose_name="Ano de Referência")
    valor = models.DecimalField(max_digits=10, decimal_places=2) # Campo correto usado no views.py
    usuario_cadastro = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='cadastros_realizados')
    data_criacao = models.DateTimeField(auto_now_add=True)
    percentual_limite_por_cliente = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=100.00,
        help_text="Percentual máximo da verba total que pode ser usado em um único cliente"
    )

    @property
    def tem_movimentacao(self):
        from solicitacoes.models import Bonificacao
        return Bonificacao.objects.filter(
            vendedor=self.vendedor,
            data_solicitacao__month=self.mes_referencia,
            data_solicitacao__year=self.ano_referencia,
            tipo='VERBA_VENDEDOR'
        ).exists()

    @property
    def limite_por_cliente(self):
        # CORREÇÃO: Alterado de self.valor_mensal para self.valor
        # Isso elimina o AttributeError apresentado na tela de erro
        return (self.valor * self.percentual_limite_por_cliente) / 100
    
    @property
    def valor_utilizado(self):
        from solicitacoes.models import Bonificacao
        from django.db.models import Sum

        bonificacoes = Bonificacao.objects.filter(
            vendedor=self.vendedor,
            data_solicitacao__month=self.mes_referencia,
            data_solicitacao__year=self.ano_referencia,
            tipo='VERBA_VENDEDOR',
            # Sugestão: incluir PENDENTE para evitar que o vendedor exceda o limite real
            status__in=['APROVADO', 'PENDENTE', 'PROCESSADO', 'FINALIZADO'] 
        )

        total = bonificacoes.aggregate(total_gasto=Sum('itens__valor_total'))['total_gasto']
        
        return total or 0

    def __str__(self):
        return f"{self.vendedor.first_name} - {self.get_mes_referencia_display()}/{self.ano_referencia}"

    class Meta:
        verbose_name = "Verba Mensal"
        verbose_name_plural = "Verbas Mensais"
        # Garante que não haja duplicidade de verba para o mesmo período e vendedor
        unique_together = ('vendedor', 'mes_referencia', 'ano_referencia')


class AcordoComercial(models.Model):
    TIPOS_ACORDO = [
        ('valor', 'Por Valor'),
        ('produto', 'Por Produto'),
    ]

    cliente_codigo = models.CharField(max_length=20)
    cliente_loja = models.CharField(max_length=10)
    cliente_nome = models.CharField(max_length=100)
    data_acordo = models.DateField()
    vigencia_inicio = models.DateField()
    vigencia_fim = models.DateField()
    tipo_acordo = models.CharField(max_length=20, choices=TIPOS_ACORDO)
    
    valor_acordo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    periodicidade = models.IntegerField(help_text="Meses", null=True, blank=True)
    
    usuario_cadastro = models.ForeignKey(User, on_delete=models.CASCADE)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.cliente_nome} - {self.get_tipo_acordo_display()}"

class AcordoItem(models.Model):
    acordo = models.ForeignKey(AcordoComercial, related_name='itens', on_delete=models.CASCADE)
    produto_codigo = models.CharField(max_length=20)
    produto_descricao = models.CharField(max_length=100)
    
    qtd_faturada = models.IntegerField(null=True, blank=True)
    qtd_bonificada = models.IntegerField(null=True, blank=True)
    
    qtd_mensal = models.IntegerField(null=True, blank=True)

class Cadastro(models.Model):

    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('CADASTRADO', 'Cadastrado no ERP'),
        ('LIBERADO', 'Liberado para Venda'),
        ('REJEITADO', 'Rejeitado'),
    ]

    plataforma = models.CharField(max_length=15, verbose_name="Plataforma")
    tipo_cliente = models.CharField(max_length=20, verbose_name="Tipo")
    razao_social = models.CharField(max_length=255, verbose_name="Razão Social")
    nome_fantasia = models.CharField(max_length=255, verbose_name="Nome Fantasia")
    cgc = models.CharField(max_length=20, verbose_name="CGC", unique=False)
    inscricao_estadual = models.CharField(max_length=20, blank=True, null=True, verbose_name="Inscrição Estadual")
    email = models.EmailField(verbose_name="Email")
    telefone = models.CharField(max_length=15, verbose_name="Telefone")
    
    cep = models.CharField(max_length=9, verbose_name="CEP")
    estado = models.CharField(max_length=2, verbose_name="Estado")
    cidade = models.CharField(max_length=100, verbose_name="Cidade")
    bairro = models.CharField(max_length=100, verbose_name="Bairro")
    endereco = models.CharField(max_length=255, verbose_name="Endereço")
    numero = models.CharField(max_length=20, verbose_name="Número")
    complemento = models.CharField(max_length=255, blank=True, null=True, verbose_name="Complemento")

    grupo_cliente = models.CharField(max_length=100, verbose_name="Grupo de Cliente")
    condicao_pagamento = models.CharField(max_length=100, verbose_name="Condição de Pagamento")
    condicao_pagamento_outro = models.CharField(max_length=100, null=True, blank=True)
    
    entrega_cep = models.CharField(max_length=9, verbose_name="CEP Entrega")
    entrega_estado = models.CharField(max_length=2, verbose_name="Estado Entrega")
    entrega_cidade = models.CharField(max_length=100, verbose_name="Cidade Entrega")
    entrega_bairro = models.CharField(max_length=100, verbose_name="Bairro Entrega")
    entrega_endereco = models.CharField(max_length=255, verbose_name="Endereço Entrega")
    entrega_numero = models.CharField(max_length=20, verbose_name="Número Entrega")
    entrega_complemento = models.CharField(max_length=100, null=True, blank=True)
    horario_entrega = models.CharField(max_length=255, blank=True, null=True, verbose_name="Horário de Entrega")

    socio_nome = models.CharField(max_length=255, null=True, blank=True)
    socio_cpf = models.CharField(max_length=20, null=True, blank=True)
    socio_cep = models.CharField(max_length=10, null=True, blank=True)
    socio_estado = models.CharField(max_length=2, null=True, blank=True)
    socio_cidade = models.CharField(max_length=100, null=True, blank=True)
    socio_bairro = models.CharField(max_length=100, null=True, blank=True)
    socio_endereco = models.CharField(max_length=255, null=True, blank=True)
    socio_numero = models.CharField(max_length=10, null=True, blank=True)
    socio_complemento = models.CharField(max_length=100, null=True, blank=True)

    finan_nome = models.CharField(max_length=255, null=True, blank=True)
    finan_cpf = models.CharField(max_length=20, null=True, blank=True)
    compra_nome = models.CharField(max_length=255, null=True, blank=True)
    compra_cpf = models.CharField(max_length=20, null=True, blank=True)

    data_cadastro = models.DateTimeField(auto_now_add=True)
    vendedor = models.ForeignKey(User, on_delete=models.CASCADE)
    situacao = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações")

    def __str__(self):
        return f"{self.razao_social} ({self.cgc})"

    class Meta:
        verbose_name = "Cadastro de Cliente"
        verbose_name_plural = "Cadastros de Clientes"
        ordering = ['-data_cadastro']

class AnexoCadastro(models.Model):
    cadastro = models.ForeignKey(Cadastro, on_delete=models.CASCADE, related_name='anexos')
    nome = models.CharField(max_length=100)
    arquivo = models.FileField(upload_to='cadastros/anexos/')
    data_upload = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nome} - {self.cadastro.razao_social}"