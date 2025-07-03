from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

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