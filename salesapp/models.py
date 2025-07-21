from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.db import models
from django.core.validators import MinValueValidator

class Cadastro(models.Model):

    plataforma = models.CharField(max_length=15, verbose_name="Plataforma")
    tipo_cliente = models.CharField(max_length=20, verbose_name="Tipo")
    razao_social = models.CharField(max_length=255, verbose_name="Razão Social")
    nome_fantasia = models.CharField(max_length=255, verbose_name="Nome Fantasia")
    cgc = models.CharField(max_length=20, verbose_name="CGC")
    inscricao_estadual = models.CharField(max_length=20, blank=True, null=True, verbose_name="Inscrição Estadual")
    email = models.EmailField(verbose_name="Email")
    telefone = models.CharField(max_length=15, verbose_name="Telefone")
    cep = models.CharField(max_length=9, verbose_name="CEP")
    estado = models.CharField(max_length=2, verbose_name="Estado")
    cidade = models.CharField(max_length=100, verbose_name="Cidade")
    bairro = models.CharField(max_length=100, verbose_name="Bairro")
    endereco = models.CharField(max_length=255, verbose_name="Endereço")
    numero = models.CharField(max_length=10, verbose_name="Número")
    complemento = models.CharField(max_length=100, blank=True, null=True, verbose_name="Complemento")
    
    grupo_cliente = models.CharField(max_length=150, verbose_name="Grupo Cliente")
    condicao_pagamento = models.CharField(max_length=20, verbose_name="Condição de Pagamento")
    condicao_pagamento_detalhe = models.CharField(max_length=255, blank=True, null=True, verbose_name="Detalhe da Condição de Pagamento (Outro)") # NOVO CAMPO: Para o "Outro"
    horario_entrega = models.CharField(max_length=20, verbose_name="Horário Entrega")
    
    cep_entrega = models.CharField(max_length=9, blank=True, null=True, verbose_name="CEP de Entrega")
    estado_entrega = models.CharField(max_length=2, blank=True, null=True, verbose_name="Estado de Entrega")
    cidade_entrega = models.CharField(max_length=100, blank=True, null=True, verbose_name="Cidade de Entrega")
    bairro_entrega = models.CharField(max_length=100, blank=True, null=True, verbose_name="Bairro de Entrega")
    endereco_entrega = models.CharField(max_length=255, blank=True, null=True, verbose_name="Endereço de Entrega")
    numero_entrega = models.CharField(max_length=10, blank=True, null=True, verbose_name="Número de Entrega")
    complemento_entrega = models.CharField(max_length=100, blank=True, null=True, verbose_name="Complemento de Entrega")

    vendedor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Vendedor Responsável", related_name='cadastros_criados')

    nome_socio = models.CharField(max_length=255, blank=True, null=True, verbose_name="Nome do Sócio")
    cpf_socio = models.CharField(max_length=14, blank=True, null=True, verbose_name="CPF do Sócio")
    cep_socio = models.CharField(max_length=9, blank=True, null=True, verbose_name="CEP do Sócio")
    estado_socio = models.CharField(max_length=2, blank=True, null=True, verbose_name="Estado do Sócio")
    cidade_socio = models.CharField(max_length=100, blank=True, null=True, verbose_name="Cidade do Sócio")
    bairro_socio = models.CharField(max_length=100, blank=True, null=True, verbose_name="Bairro do Sócio")
    endereco_socio = models.CharField(max_length=255, blank=True, null=True, verbose_name="Endereço do Sócio")
    numero_socio = models.CharField(max_length=10, blank=True, null=True, verbose_name="Número do Sócio")
    complemento_socio = models.CharField(max_length=100, blank=True, null=True, verbose_name="Complemento do Sócio")

    nome_financeiro = models.CharField(max_length=255, blank=True, null=True, verbose_name="Nome Financeiro")
    telefone_financeiro = models.CharField(max_length=15, blank=True, null=True, verbose_name="Telefone Financeiro")

    nome_compras = models.CharField(max_length=255, blank=True, null=True, verbose_name="Nome Compras")
    telefone_compras = models.CharField(max_length=15, blank=True, null=True, verbose_name="Telefone Compras")

    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('cadastrado', 'Cadastrado'),
        ('liberado', 'Liberado'),
        ('rejeitado', 'Rejeitado'),
    ]
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pendente',
        verbose_name="Status do Cadastro"
    )

    motivo_rejeicao = models.TextField(blank=True, null=True, verbose_name="Motivo da Rejeição")
    data_cadastro = models.DateTimeField(auto_now_add=True, verbose_name="Data de Cadastro")
    data_atualizacao = models.DateTimeField(auto_now=True, verbose_name="Última Atualização")

    data_aprovacao_cadastro = models.DateTimeField(null=True, blank=True, verbose_name="Data Aprovação Cadastro")
    obs_cadastro = models.TextField(null=True, blank=True, verbose_name="Observação do Cadastro")
    data_aprovacao_financeiro = models.DateTimeField(null=True, blank=True, verbose_name="Data Aprovação Financeiro")
    obs_financeiro = models.TextField(null=True, blank=True, verbose_name="Observação do Financeiro")

    @property
    def situacao_display(self):
        """Retorna o texto amigável para o status do cadastro na tabela."""
        status_map = {
            'pendente': 'Pendente (Cadastro)',
            'cadastrado': 'Pendente (Financeiro)',
            'liberado': 'Aprovado',
            'rejeitado': 'Rejeitado',
        }
        return status_map.get(self.status, 'Desconhecido')

    @property
    def situacao_cor(self):
        """Retorna a classe CSS para a cor do status-dot."""
        if self.status == 'liberado':
            return 'verde'
        elif self.status == 'rejeitado':
            return 'vermelho'
        elif self.status in ['pendente', 'cadastrado']:
            return 'amarelo' 
        return ''
    
    class Meta:
        verbose_name = "Cadastro"
        verbose_name_plural = "Cadastros"
        ordering = ['-data_cadastro']

    def __str__(self):
        return f"{self.razao_social} ({self.cgc}) - {self.status}"

class AnexoCadastro(models.Model):
    cadastro = models.ForeignKey(
        Cadastro,
        on_delete=models.CASCADE,
        related_name='anexos',
        verbose_name="Cadastro Relacionado"
    )
    arquivo = models.FileField(
        upload_to='cadastros/anexos_especificos/',
        verbose_name="Arquivo Anexado"
    )
    descricao = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Descrição do Anexo"
    )
    data_upload = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Anexo de Cadastro"
        verbose_name_plural = "Anexos de Cadastros"
        ordering = ['-data_upload']

    def __str__(self):
        return f"Anexo para {self.cadastro.razao_social} - {self.descricao or self.arquivo.name}"
    
class TotvsVendedor(models.Model):
    cod_vendedor = models.CharField(max_length=6, primary_key=True)
    nome_vendedor = models.CharField(max_length=100, null=True, blank=True)
    email_vendedor = models.EmailField(max_length=80, unique=True)

    class Meta:
        db_table = 'totvs_vendedores'
        verbose_name = 'Vendedor TOTVS'
        verbose_name_plural = 'Vendedores TOTVS'

    def __str__(self):
        return f"{self.nome_vendedor} ({self.cod_vendedor})"

class TotvsCliente(models.Model):
    cod_cliente = models.CharField(max_length=8)
    loja_cliente = models.CharField(max_length=4)
    razao_social = models.CharField(max_length=100, null=True, blank=True)
    nome_fantasia = models.CharField(max_length=100, null=True, blank=True)
    cgc = models.CharField(max_length=20, null=True, blank=True)
    grp_cliente = models.CharField(max_length=100, null=True, blank=True)
    desc_grupo = models.CharField(max_length=20, null=True, blank=True)
    cod_vendedor = models.ForeignKey(
        TotvsVendedor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        to_field='cod_vendedor',
        db_column='cod_vendedor'
    )

    class Meta:
        db_table = 'totvs_clientes'
        verbose_name = 'Cliente TOTVS'
        verbose_name_plural = 'Clientes TOTVS'
        unique_together = (('cod_cliente', 'loja_cliente'),)

    def __str__(self):
        return f"{self.razao_social} ({self.cod_cliente}-{self.loja_cliente})"

class TotvsProduto(models.Model):
    cod_produto = models.CharField(max_length=20, primary_key=True)
    desc_produto = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = 'totvs_produtos'

class TotvsTabPreco(models.Model):
    cod_produto = models.OneToOneField(
        TotvsProduto,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column='cod_produto',
        to_field='cod_produto'
    )
    grp_cliente = models.CharField(max_length=6, null=True, blank=True)
    vlr_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'totvs_tab_preco'
        verbose_name = 'Tabela de Preço TOTVS'
        verbose_name_plural = 'Tabelas de Preço TOTVS'

    def __str__(self):
        return f"Preço {self.vlr_unitario} para {self.cod_produto.cod_produto} (Grupo: {self.grp_cliente})"

class Bonificacao(models.Model):
    cod_cliente = models.CharField(max_length=20, verbose_name="Código do Cliente")
    loja_cliente = models.CharField(max_length=4, verbose_name="Loja do Cliente")
    razao_social = models.CharField(max_length=255, verbose_name="Razão Social")
    nome_fantasia = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome Fantasia")
    cgc = models.CharField(max_length=18, verbose_name="CNPJ/CPF")
    grupo_cliente = models.CharField(max_length=50, verbose_name="Grupo do Cliente")
    motivo = models.TextField(verbose_name="Motivo da Bonificação")
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Total")
    numero_pedido = models.CharField(max_length=10, null=True, blank=True, verbose_name="Pedido de Venda")
    
    vendedor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Vendedor Responsável")
    
    data_criacao = models.DateTimeField(auto_now_add=True, verbose_name="Data de Cadastro")
    data_aprovacao_gestor = models.DateTimeField(null=True, blank=True, verbose_name="Data de Aprovação do Gestor")
    obs_gestor = models.TextField(null=True, blank=True, verbose_name="Observação do Gestor")
    data_aprovacao_diretoria = models.DateTimeField(null=True, blank=True, verbose_name="Data de Aprovação da Diretoria")
    obs_diretoria = models.TextField(null=True, blank=True, verbose_name="Observação da Diretoria")
    data_pedido = models.DateTimeField(null=True, blank=True, verbose_name="Data de Geração do Pedido")
    obs_pedido = models.TextField(null=True, blank=True, verbose_name="Observação do Pedido")


    TIPO_BONIFICACAO_CHOICES = [
        ('VERBA_CONTRATO', 'Verba Contrato'),
        ('BONIFICACAO_VERBA', 'Bonificação Dentro da Verba'),
        ('NEGOCIACAO_ESPECIAL', 'Negociação Especial'),
    ]

    tipo_bonificacao = models.CharField(
        max_length=50,
        choices=TIPO_BONIFICACAO_CHOICES,
        default='NEGOCIACAO_ESPECIAL' # Defina um default se apropriado
    )

    motivo_recusa = models.TextField(null=True, blank=True, verbose_name="Motivo da Recusa")

    STATUS_CHOICES = [
        ('PENDENTE_GESTOR', 'Pendente Aprovação'),
        ('PENDENTE_PEDIDO', 'Pendente Pedido'),
        ('RECUSADA', 'Recusada'),
        ('PEDIDO_GERADO', 'Pedido Gerado'),
    ]
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='PENDENTE_GESTOR', verbose_name="Status")

    @property
    def status_display(self):
        """Retorna o texto amigável para o status do cadastro na tabela."""
        status_map = {
            'PENDENTE_GESTOR': 'Pendente Aprovação',
            'PENDENTE_PEDIDO': 'Pendente Pedido',
            'RECUSADA': 'Recusada',
            'PEDIDO_GERADO': 'Pedido Gerado',
        }
        return status_map.get(self.status, 'Desconhecido')

    @property
    def status_cor(self):
        """Retorna a classe CSS para a cor do status-dot."""
        if self.status == 'PEDIDO_GERADO':
            return 'verde'
        elif self.status == 'RECUSADA':
            return 'vermelho'
        elif self.status in ['PENDENTE_GESTOR', 'PENDENTE_DIRETORIA', 'PENDENTE_PEDIDO']:
            return 'amarelo' 
        return ''

    class Meta:
        verbose_name = "Bonificação"
        verbose_name_plural = "Bonificações"
        indexes = [
            models.Index(fields=['cod_cliente', 'loja_cliente']),
        ]

    def __str__(self):
        return f"Bonificação para {self.razao_social} (ID: {self.id})"

class ItemBonificacao(models.Model):
    
    bonificacao = models.ForeignKey(
        Bonificacao, 
        on_delete=models.CASCADE,
        related_name='itens',
        verbose_name="Bonificação Relacionada"
    )
    cod_produto = models.CharField(max_length=50, verbose_name="Código do Produto")
    desc_produto = models.CharField(max_length=255, verbose_name="Descrição do Produto")
    preco_tabela = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço Tabela")
    quantidade = models.IntegerField(validators=[MinValueValidator(1)], verbose_name="Quantidade")
    valor_total_item = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Total do Item")

    class Meta:
        verbose_name = "Item de Bonificação"
        verbose_name_plural = "Itens de Bonificação"

    def save(self, *args, **kwargs):
        self.valor_total_item = self.preco_tabela * self.quantidade
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"Item {self.cod_produto} - {self.desc_produto} (Qtd: {self.quantidade})"
