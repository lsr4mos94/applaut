"""
Cria agendamentos de chopp de TESTE para validar o Agendamento e a tela do Chopp.

    python manage.py popular_agendamentos_teste            # cria (hoje e os próximos 6 dias, sem domingo)
    python manage.py popular_agendamentos_teste --limpar   # apaga só o que este comando criou
    python manage.py popular_agendamentos_teste --limpar --tudo   # apaga TODOS os pedidos de chopp (base de teste)

Usa clientes, condições de pagamento, produtos e preços REAIS do Protheus (CIEC 01, filial 0101),
para que editar, ver inadimplência e processar funcionem como em produção.
Os registros criados ficam marcados com "[TESTE]" na observação.

- Pendentes: alguns pedidos sem dia, para o backoffice distribuir.
- Hoje: confirmado (Enviado e algum Cancelado).
- Próximos dias: Agendados (e um ou outro cancelado pelo vendedor), prontos para confirmar.
Não roda com DEBUG=False (produção), a menos que se use --forcar.
"""
import random
from datetime import time, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from app.protheus import ProtheusIndisponivel
from solicitacoes import agendamento as regras
from solicitacoes import protheus_chopp
from solicitacoes.models import DiaConfirmadoChopp, SolicitacaoChopp, SolicitacaoChoppItem

MARCA = '[TESTE]'
OBSERVACOES = ['', '', '', 'Cliente chega com caminhão próprio.', 'Ligar antes de separar.', 'Retirada pelo motorista Carlos.']


class Command(BaseCommand):
    help = "Cria agendamentos de chopp de teste (hoje e os próximos 6 dias) com dados reais do Protheus."

    def add_arguments(self, parser):
        parser.add_argument('--limpar', action='store_true', help="Apaga os agendamentos de teste criados por este comando.")
        parser.add_argument('--tudo', action='store_true',
                            help="Com --limpar: apaga TODOS os pedidos de chopp e dias confirmados (não só os de teste).")
        parser.add_argument('--por-dia', type=int, default=4, help="Média de agendamentos por dia (padrão 4).")
        parser.add_argument('--pendentes', type=int, default=6, help="Pedidos ainda sem dia, na coluna de pendentes (padrão 6).")
        parser.add_argument('--forcar', action='store_true', help="Permite rodar com DEBUG=False (não use em produção).")

    def handle(self, *args, **opt):
        if not settings.DEBUG and not opt['forcar']:
            raise CommandError("DEBUG=False: parece produção. Rode só na base de teste (ou use --forcar se tiver certeza).")
        if opt['limpar']:
            return self.limpar_tudo() if opt['tudo'] else self.limpar()

        vendedores = list(User.objects.filter(groups__name='Vendedores', is_active=True).distinct())
        gestor = User.objects.filter(groups__name='Gestão Comercial', is_active=True).first()
        faturamento = User.objects.filter(groups__name='Faturamento', is_active=True).first() or gestor
        if not vendedores or not gestor:
            raise CommandError("É preciso ter pelo menos um usuário em 'Vendedores' e um em 'Gestão Comercial'.")

        self.stdout.write("Consultando clientes e produtos no Protheus...")
        try:
            clientes = protheus_chopp.clientes_ao_acaso(40)
            produtos = protheus_chopp.listar_produtos()
            precos_por_tabela = {}
            for tabela in {c['tabela'] for c in clientes}:
                precos_por_tabela[tabela] = protheus_chopp.precos_tabela(tabela, [p['codigo'] for p in produtos])
        except ProtheusIndisponivel as e:
            raise CommandError(f"Protheus indisponível: {e}")

        # só clientes cuja tabela tem preço para algum produto de chopp
        clientes = [c for c in clientes if precos_por_tabela.get(c['tabela'])]
        if not clientes:
            raise CommandError("Nenhum cliente com condição de pagamento e tabela de preço com produtos de chopp.")
        nomes = {p['codigo']: p['descricao'] for p in produtos}
        # barris primeiro (são o que mais se agenda); copos e acessórios de vez em quando
        def barris(precos):
            return [c for c in precos if 'BARRIL' in nomes.get(c, '')] or list(precos)

        hoje = regras.hoje()
        inicio, fim = regras.periodo_calendario()
        criados = 0
        with transaction.atomic():
            dia = inicio
            while dia <= fim:
                if dia.weekday() == 6:
                    dia += timedelta(days=1)
                    continue
                confirmado = dia <= hoje
                qtd = max(1, opt['por_dia'] + random.randint(-1, 2) - (2 if dia.weekday() == 5 else 0))
                for n in range(qtd + opt['pendentes'] if dia == inicio else qtd):
                    pendente = dia == inicio and n >= qtd      # alguns pedidos ainda sem dia
                    ultima = 11 if dia.weekday() == 5 else 18
                    hora = time(random.randint(6, ultima), random.choice([0, 15, 30, 45]))
                    cli = random.choice(clientes)
                    precos = precos_por_tabela[cli['tabela']]
                    if pendente:
                        status = 'PENDENTE'
                    elif confirmado:
                        status = random.choices(['FINALIZADO', 'ENVIADO', 'CANCELADO'], [5, 3, 1])[0] if dia < hoje else \
                            random.choices(['ENVIADO', 'CANCELADO'], [6, 1])[0]
                    else:
                        status = random.choices(['AGENDADO', 'CANCELADO'], [9, 1])[0]
                    ag = SolicitacaoChopp.objects.create(
                        vendedor=random.choice(vendedores),
                        cliente_codigo=cli['codigo'], cliente_loja=cli['loja'],
                        cliente_razao_social=cli['nome'][:100], cliente_nome_fantasia=cli['fantasia'][:100],
                        cliente_cpf_cnpj=cli['cnpj'][:18],
                        condicao_pagamento=cli['condicao'][:10],
                        condicao_pagamento_descricao=(cli['condicao_descricao'] or cli['condicao'])[:60],
                        tabela_preco=cli['tabela'][:10],
                        data_retirada=None if pendente else dia, hora_retirada=None if pendente else hora,
                        agendado_por=None if pendente else gestor, agendado_em=None if pendente else timezone.now(),
                        observacao=(f"{MARCA} {random.choice(OBSERVACOES)}").strip(),
                        status=status,
                    )
                    escolhidos = random.sample(barris(precos), k=min(len(barris(precos)), random.choice([1, 1, 2])))
                    if random.random() < 0.25:
                        extras = [c for c in precos if c not in escolhidos]
                        if extras:
                            escolhidos.append(random.choice(extras))
                    for cod in escolhidos:
                        q = random.randint(1, 6)
                        SolicitacaoChoppItem.objects.create(
                            solicitacao=ag, produto_codigo=cod, produto_descricao=nomes.get(cod, cod)[:100],
                            quantidade=q, preco_unitario=precos[cod], qtd_solicitada=q, preco_solicitado=precos[cod],
                            preco_da_tabela=True)
                    if status == 'FINALIZADO':
                        ag.pedido_protheus = f"{random.randint(0, 999999):06d}"
                        ag.usuario_faturamento = faturamento
                        ag.data_finalizacao = timezone.now()
                        item = ag.itens.first()
                        if random.random() < 0.3 and item.quantidade > 1:   # faturamento ajustou a quantidade
                            item.quantidade -= 1
                            item.save()
                            ag.alterado_pelo_faturamento = True
                            ag.observacao_faturamento = f"{MARCA} Cliente levou uma unidade a menos."
                        ag.save()
                    elif status == 'CANCELADO':
                        ag.motivo_cancelamento = 'Cliente remarcou a retirada.' if not confirmado else 'Cliente não compareceu.'
                        ag.cancelado_por = random.choice(vendedores) if not confirmado else faturamento
                        ag.data_cancelamento = timezone.now()
                        ag.save()
                    criados += 1
                if confirmado:
                    DiaConfirmadoChopp.objects.get_or_create(data=dia, defaults={'confirmado_por': gestor})
                dia += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(
            f"{criados} agendamentos de teste criados de {inicio:%d/%m} a {fim:%d/%m} "
            f"({len(clientes)} clientes reais). Hoje ficou confirmado."))
        self.stdout.write("Para apagar depois: python manage.py popular_agendamentos_teste --limpar")

    def limpar_tudo(self):
        with transaction.atomic():
            total = SolicitacaoChopp.objects.count()
            SolicitacaoChopp.objects.all().delete()           # os itens vão junto
            dias = DiaConfirmadoChopp.objects.count()
            DiaConfirmadoChopp.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"{total} pedidos de chopp e {dias} dia(s) confirmado(s) apagados."))

    def limpar(self):
        with transaction.atomic():
            testes = SolicitacaoChopp.objects.filter(observacao__startswith=MARCA)
            datas = set(testes.values_list('data_retirada', flat=True))
            total = testes.count()
            testes.delete()
            # confirmação só sai se o dia ficou sem nenhum agendamento
            dias = [d for d in datas if d and not SolicitacaoChopp.objects.filter(data_retirada=d).exists()]
            DiaConfirmadoChopp.objects.filter(data__in=dias).delete()
        self.stdout.write(self.style.SUCCESS(f"{total} agendamentos de teste apagados; {len(dias)} dia(s) desconfirmado(s)."))
