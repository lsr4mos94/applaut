"""
Testes automáticos do Sistema Läut.

Rodar com:  python manage.py test app
O Protheus e a Zenvia são simulados; nenhum teste acessa sistemas externos.
"""
import base64
import os
import tempfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings

from adm.models import SolicitacaoVerba
from cadastros.models import AcordoComercial, AcordoItem, AnexoCadastro, Cadastro, VerbaMensal
from solicitacoes.models import Bonificacao, BonificacaoItem, Plantao, SolicitacaoChopp, SolicitacaoChoppItem

PRECO_TABELA = Decimal('100.00')


def precos_falsos(codigos):
    return {c: PRECO_TABELA for c in codigos}


class Base(TestCase):
    """Usuários de cada grupo e helpers para criar registros."""

    def usuario(self, nome, *grupos):
        u = User.objects.create_user(nome, password='x', email=f'{nome}@teste.com', first_name=nome.title())
        for g in grupos:
            u.groups.add(Group.objects.get_or_create(name=g)[0])
        c = Client()
        c.force_login(u)
        return u, c

    def setUp(self):
        self.vend, self.cv = self.usuario('vend', 'Vendedores')
        self.vend2, self.cv2 = self.usuario('vend2', 'Vendedores')
        self.ges, self.cg = self.usuario('ges', 'Gestão Comercial')
        self.fat, self.cf = self.usuario('fat', 'Faturamento')
        self.fin, self.cfin = self.usuario('fin', 'Gestão Financeira')
        self.cap, self.ccap = self.usuario('cap', 'Contas a Pagar')
        self.pla, self.cpla = self.usuario('pla', 'Plantao')
        self.cad, self.ccad = self.usuario('cad', 'Cadastro')
        self.anon = Client()
        patcher = mock.patch('solicitacoes.views.buscar_precos_protheus', side_effect=precos_falsos)
        patcher.start()
        self.addCleanup(patcher.stop)

    def bonificacao(self, status='PENDENTE', vendedor=None, tipo='NEGOCIACAO_ESPECIAL', valor='10'):
        b = Bonificacao.objects.create(
            tipo=tipo, vendedor=vendedor or self.vend, cliente_codigo='1', cliente_loja='01',
            cliente_razao_social='CLIENTE', cliente_nome_fantasia='CLIENTE', cliente_cpf_cnpj='1',
            justificativa='j', status=status)
        BonificacaoItem.objects.create(bonificacao=b, produto_codigo='1', produto_descricao='CHOPP',
                                       preco_tabela=Decimal(valor), quantidade=1)
        return b

    def plantao(self, vendedor=None):
        return Plantao.objects.create(
            codigo_cliente='1', loja_cliente='01', nome_cliente='X', cep='1', estado='SP', cidade='SP',
            bairro='B', endereco='E', numero='1', vendedor=vendedor or self.vend, tipo='TECNICO',
            ocorrencia='OUTRO', horario=time(10, 0))

    def cadastro(self, situacao='PENDENTE', vendedor=None):
        return Cadastro.objects.create(
            plataforma='CIEC', tipo_cliente='PJ', razao_social='C', nome_fantasia='C', cgc='1',
            email='a@a.com', telefone='1', cep='1', estado='SP', cidade='SP', bairro='B', endereco='E',
            numero='1', grupo_cliente='G', condicao_pagamento='C', entrega_cep='1', entrega_estado='SP',
            entrega_cidade='SP', entrega_bairro='B', entrega_endereco='E', entrega_numero='1',
            vendedor=vendedor or self.vend, situacao=situacao)

    def solicitacao_verba(self, status='PENDENTE', usuario=None):
        return SolicitacaoVerba.objects.create(
            usuario_solicitante=usuario or self.vend, fornecedor_nome_razao='F', fornecedor_cpf_cnpj='1',
            produto_servico='P', categoria=SolicitacaoVerba.CATEGORIAS_CHOICES[0][0],
            forma_pagamento=SolicitacaoVerba.FORMA_PAGAMENTO_CHOICES[0][0], valor=Decimal('10'),
            data_vencimento=date(2030, 12, 1), status=status)

    def post_bonificacao(self, client, tipo='VERBA_VENDEDOR', qtd=1, codigo='000210', extra=None):
        dados = {'tipo': tipo, 'cliente_razao_social': 'X', 'cliente_cpf_cnpj': '1', 'cliente_codigo': '1',
                 'cliente_loja': '01', 'item_nome_1': 'PRODUTO', 'item_codigo_1': codigo,
                 'item_preco_1': '0.01', 'item_qtd_1': str(qtd), 'justificativa': 'j'}
        dados.update(extra or {})
        return client.post('/solicitacoes/bonificacoes/nova/', dados)


# ---------------------------------------------------------------------------------------- acesso
class AcessoSemLoginTests(Base):
    def test_rotas_exigem_login(self):
        for url in ['/', '/cadastros/cadastros/exportar/excel/', '/solicitacoes/bonificacoes/exportar/excel/',
                    '/adm/verba/exportar/excel/', '/solicitacoes/plantoes/', '/solicitacoes/plantoes/detalhes/1/',
                    '/cadastros/buscar-vendedor/?codigo=1', '/solicitacoes/api/busca-produtos/?q=abc',
                    '/media/qualquer.pdf']:
            r = self.anon.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn('/accounts/login/', r.url, url)

    def test_anonimo_nao_edita_verba(self):
        verba = VerbaMensal.objects.create(vendedor=self.vend, mes_referencia=1, ano_referencia=2030,
                                           valor=Decimal('5000'), usuario_cadastro=self.ges)
        self.anon.post(f'/cadastros/verbas/editar/{verba.pk}/', {'valor': '99999', 'mes': 1, 'ano': 2030})
        verba.refresh_from_db()
        self.assertEqual(verba.valor, Decimal('5000'))


class BonificacaoPermissaoTests(Base):
    def test_aprovar_so_por_post_e_so_gestao(self):
        b = self.bonificacao()
        url = f'/solicitacoes/bonificacoes/gerenciar/{b.id}/aprovar/'
        self.cg.get(url)
        self.cv.post(url)
        self.cf.post(url)
        b.refresh_from_db()
        self.assertEqual(b.status, 'PENDENTE')
        mail.outbox = []
        self.cg.post(url)
        b.refresh_from_db()
        self.assertEqual(b.status, 'APROVADO')
        self.assertEqual(len(mail.outbox), 1, 'e-mail de aprovação deve ser enviado')

    def test_concluir_so_faturamento_e_aprovada(self):
        b = self.bonificacao('APROVADO')
        url = f'/solicitacoes/bonificacoes/gerenciar/{b.id}/concluir/'
        self.cg.post(url, {'pedido_erp': '1'})
        b.refresh_from_db()
        self.assertEqual(b.status, 'APROVADO')
        self.cf.post(url, {'pedido_erp': '123'})
        b.refresh_from_db()
        self.assertEqual((b.status, b.pedido_protheus), ('CONCLUIDO', '123'))

    def test_excluir_so_gestao_por_post(self):
        b = self.bonificacao()
        self.cf.post(f'/solicitacoes/bonificacao/excluir/{b.id}/')
        self.cg.get(f'/solicitacoes/bonificacao/excluir/{b.id}/')
        self.assertTrue(Bonificacao.objects.filter(pk=b.pk).exists())
        self.cg.post(f'/solicitacoes/bonificacao/excluir/{b.id}/')
        self.assertFalse(Bonificacao.objects.filter(pk=b.pk).exists())

    def test_pdf_so_dono_ou_gestao(self):
        b = self.bonificacao()
        self.assertEqual(self.cv.get(f'/solicitacoes/bonificacoes/pdf/{b.id}/').status_code, 200)
        self.assertEqual(self.cv2.get(f'/solicitacoes/bonificacoes/pdf/{b.id}/').status_code, 404)
        self.assertEqual(self.cg.get(f'/solicitacoes/bonificacoes/pdf/{b.id}/').status_code, 200)

    def test_exportar_so_gestao(self):
        self.assertEqual(self.cv.get('/solicitacoes/bonificacoes/exportar/excel/').status_code, 302)
        self.assertEqual(self.cg.get('/solicitacoes/bonificacoes/exportar/excel/').status_code, 200)


class VerbaMensalTests(Base):
    def setUp(self):
        super().setUp()
        hoje = date.today()
        self.verba = VerbaMensal.objects.create(vendedor=self.vend, mes_referencia=hoje.month,
                                                ano_referencia=hoje.year, valor=Decimal('1000'),
                                                usuario_cadastro=self.ges)

    def test_vendedor_nao_cria_nem_edita_verba(self):
        self.cv.post('/cadastros/verbas/salvar/', {'vendedor_id': self.vend.id, 'mes': 1, 'ano': 2031, 'valor': '50000'})
        self.assertFalse(VerbaMensal.objects.filter(ano_referencia=2031).exists())
        self.cv.post(f'/cadastros/verbas/editar/{self.verba.pk}/', {'valor': '9999', 'mes': 1, 'ano': 2031, 'percentual_limite': '100'})
        self.verba.refresh_from_db()
        self.assertEqual(self.verba.valor, Decimal('1000'))

    def test_saldo_conta_pendente_aprovada_concluida(self):
        for status, valor in [('PENDENTE', '100'), ('APROVADO', '200'), ('CONCLUIDO', '300'), ('REPROVADO', '999')]:
            self.bonificacao(status, tipo='VERBA_VENDEDOR', valor=valor)
        self.assertEqual(self.verba.valor_utilizado, Decimal('600'))

    def test_bonificacao_respeita_saldo_com_preco_do_protheus(self):
        # 10 x R$ 100 = 1000 cabe; mais 1 não cabe
        self.post_bonificacao(self.cv, qtd=10)
        self.assertEqual(Bonificacao.objects.count(), 1)
        item = BonificacaoItem.objects.get()
        self.assertEqual(item.preco_tabela, PRECO_TABELA, 'preço digitado na tela deve ser ignorado')
        self.post_bonificacao(self.cv, qtd=1)
        self.assertEqual(Bonificacao.objects.count(), 1)

    def test_quantidade_invalida_recusada(self):
        self.post_bonificacao(self.cv, qtd=0)
        self.post_bonificacao(self.cv, qtd=-3)
        self.assertEqual(Bonificacao.objects.count(), 0)

    def test_protheus_fora_do_ar_nao_grava(self):
        from app.protheus import ProtheusIndisponivel
        with mock.patch('solicitacoes.views.buscar_precos_protheus', side_effect=ProtheusIndisponivel('fora')):
            r = self.post_bonificacao(self.cv, qtd=1)
        self.assertEqual(Bonificacao.objects.count(), 0)
        self.assertContains(r, 'Protheus')


class AcordoComercialTests(Base):
    def acordo(self, tipo='produto', valor=None, qtd=10):
        a = AcordoComercial.objects.create(
            cliente_codigo='1', cliente_loja='01', cliente_nome='XPTO', data_acordo=date.today(),
            vigencia_inicio=date.today(), vigencia_fim=date.today() + timedelta(days=90),
            tipo_acordo=tipo, valor_acordo=valor, usuario_cadastro=self.ges)
        if tipo == 'produto':
            AcordoItem.objects.create(acordo=a, produto_codigo='BARRIL', produto_descricao='Barril', qtd_faturada=qtd)
        return a

    def pedir(self, acordo, qtd):
        return self.post_bonificacao(self.cv, tipo='ACORDO_COMERCIAL', qtd=qtd, codigo='BARRIL',
                                     extra={'acordo_id_global': str(acordo.id)})

    def test_saldo_consumido_e_encerramento_automatico(self):
        a = self.acordo()
        self.pedir(a, 6)
        a.refresh_from_db()
        self.assertEqual((a.situacao, a.saldo_disponivel), ('ATIVO', 4))
        self.pedir(a, 5)
        self.assertEqual(Bonificacao.objects.count(), 1, 'acima do saldo deve ser recusado')
        self.pedir(a, 4)
        a.refresh_from_db()
        self.assertEqual((a.situacao, a.saldo_disponivel), ('ENCERRADO', 0))

    def test_excluir_bonificacao_reabre_acordo(self):
        a = self.acordo(qtd=2)
        self.pedir(a, 2)
        a.refresh_from_db()
        self.assertEqual(a.situacao, 'ENCERRADO')
        self.cg.post(f'/solicitacoes/bonificacao/excluir/{Bonificacao.objects.get().id}/')
        a.refresh_from_db()
        self.assertEqual((a.situacao, a.saldo_disponivel), ('ATIVO', 2))

    def test_so_gestao_inclui_acordo(self):
        dados = {'cliente_codigo': '1', 'cliente_loja': '01', 'cliente_nome': 'X', 'vigencia_inicio': '2030-01-01',
                 'vigencia_fim': '2030-12-31', 'tipo_acordo': 'valor', 'valor_acordo': '100'}
        self.cv.post('/cadastros/acordos/salvar/', dados)
        self.assertEqual(AcordoComercial.objects.count(), 0)
        ambos, c_ambos = self.usuario('ambos', 'Vendedores', 'Gestão Comercial')
        c_ambos.post('/cadastros/acordos/salvar/', dados)
        self.assertEqual(AcordoComercial.objects.count(), 1)


class CadastroClienteTests(Base):
    def test_fluxo_de_aprovacao_por_grupo(self):
        c = self.cadastro()
        self.cv.post(f'/cadastros/clientes/{c.pk}/status/', {'acao': 'reprovar'})
        c.refresh_from_db()
        self.assertEqual(c.situacao, 'PENDENTE')
        self.ccad.post(f'/cadastros/clientes/{c.pk}/status/', {'acao': 'aprovar'})
        c.refresh_from_db()
        self.assertEqual(c.situacao, 'CADASTRADO')

    def test_detalhes_e_anexos_so_para_quem_pode(self):
        c = self.cadastro()
        self.assertEqual(self.cv2.get(f'/cadastros/clientes/{c.pk}/detalhes/').status_code, 404)
        self.assertEqual(self.ccad.get(f'/cadastros/clientes/{c.pk}/detalhes/').status_code, 200)
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            anexo = AnexoCadastro(cadastro=c, nome='Contrato Social')
            anexo.arquivo.save('contrato.pdf', ContentFile(b'%PDF'), save=True)
            url = '/media/' + anexo.arquivo.name
            self.assertEqual(self.anon.get(url).status_code, 302)
            self.assertEqual(self.cv2.get(url).status_code, 404)
            self.assertEqual(self.cv.get(url).status_code, 200)


class PlantaoTests(Base):
    def test_confirmar_so_equipe_e_excluir_so_dono(self):
        p = self.plantao()
        self.cv.post('/solicitacoes/plantoes/', {'plantao_id': p.id})
        p.refresh_from_db()
        self.assertEqual(p.status, 'PENDENTE')
        self.cpla.post('/solicitacoes/plantoes/', {'plantao_id': p.id})
        p.refresh_from_db()
        self.assertEqual(p.status, 'CONFIRMADO')
        p2 = self.plantao()
        self.cv2.post(f'/solicitacoes/plantoes/excluir/{p2.id}/')
        self.assertTrue(Plantao.objects.filter(pk=p2.pk).exists())
        self.cv.post(f'/solicitacoes/plantoes/excluir/{p2.id}/')
        self.assertFalse(Plantao.objects.filter(pk=p2.pk).exists())

    @override_settings(WEBHOOK_PLANTAO_TOKEN='chave-certa')
    def test_webhook_exige_chave(self):
        p = self.plantao()
        p.zenvia_message_id = 'abc'
        p.save()
        corpo = '{"message": {"idRef": "abc", "contents": [{"text": "ATENDIDA"}]}}'
        r = self.anon.post('/webhook_plantao/zenvia/', corpo, content_type='application/json', HTTP_X_API_KEY='errada')
        self.assertEqual(r.status_code, 401)
        r = self.anon.post('/webhook_plantao/zenvia/', corpo, content_type='application/json', HTTP_X_API_KEY='chave-certa')
        p.refresh_from_db()
        self.assertEqual((r.status_code, p.status), (200, 'CONFIRMADO'))

    @override_settings(ZENVIA_API_TOKEN='')
    def test_sem_token_zenvia_nao_chama_api(self):
        from solicitacoes import views
        with mock.patch.object(views.requests, 'post') as post:
            resultado = views.disparar_plantao_whatsapp(self.plantao())
        self.assertFalse(post.called)
        self.assertFalse(resultado['sucesso'])


class VerbaAdministrativaTests(Base):
    def test_concluir_salva_titulo_e_so_contas_a_pagar(self):
        s = self.solicitacao_verba('APROVADO')
        self.cv.post(f'/adm/verba/concluir/{s.pk}/', {'num_titulo': '1'})
        s.refresh_from_db()
        self.assertEqual(s.status, 'APROVADO')
        self.ccap.post(f'/adm/verba/concluir/{s.pk}/', {'num_titulo': '000123'})
        s.refresh_from_db()
        self.assertEqual((s.status, s.num_titulo), ('CONCLUIDO', '000123'))

    def test_detalhes_so_dono_ou_financeiro(self):
        s = self.solicitacao_verba()
        self.assertEqual(self.cv2.get(f'/adm/verba/detalhes/{s.pk}/').status_code, 403)
        self.assertEqual(self.cfin.get(f'/adm/verba/detalhes/{s.pk}/').status_code, 200)


class BoletoTests(Base):
    def test_busca_por_ano_e_bloqueio_fora_da_pasta(self):
        from django.core.cache import cache
        from solicitacoes import views
        raiz = tempfile.mkdtemp()
        agora = datetime.now()
        pasta = os.path.join(raiz, str(agora.year), 'sub')
        os.makedirs(pasta)
        arquivo = os.path.join(pasta, 'NF555_boleto.pdf')
        open(arquivo, 'w').write('%PDF')
        cache.delete('indice_boletos')
        with mock.patch.object(views, 'PASTA_BOLETOS', raiz):
            r = self.cv.post('/solicitacoes/boletos/', {'numero_nota': '555'})
            self.assertContains(r, 'NF555_boleto.pdf')
            codigo = base64.urlsafe_b64encode(arquivo.encode()).decode()
            self.assertEqual(self.cv.get(f'/solicitacoes/boletos/baixar/{codigo}/').status_code, 200)
            fora = base64.urlsafe_b64encode(b'/etc/hostname').decode()
            self.assertEqual(self.cv.get(f'/solicitacoes/boletos/baixar/{fora}/').status_code, 404)
        cache.delete('indice_boletos')


class ProtheusTests(Base):
    def test_busca_de_produto_avisa_quando_protheus_esta_fora(self):
        from app.protheus import ProtheusIndisponivel
        with mock.patch('solicitacoes.views.buscar_produtos_protheus', side_effect=ProtheusIndisponivel('x')):
            r = self.cv.get('/solicitacoes/api/busca-produtos/?q=chopp')
        self.assertEqual(r.status_code, 503)
        self.assertIn('erro', r.json())

    def test_consulta_usa_parametros(self):
        from app import protheus
        executadas = []

        class Cursor:
            description = [('A',)]
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def execute(self, sql, params): executadas.append((sql, params))
            def fetchall(self): return [('1',)]

        class Conexao:
            def cursor(self): return Cursor()

        with mock.patch.object(protheus, 'connections', {'protheus_ciec': Conexao()}):
            protheus.consultar({'protheus_ciec': ['SB1010']}, "SELECT A FROM {tabela} WHERE B = %s", ["x' OR 1=1"])
        sql, params = executadas[0]
        self.assertNotIn('OR 1=1', sql)
        self.assertEqual(params, ["x' OR 1=1"])


class ChoppTests(Base):
    def post_chopp(self, client, url='/solicitacoes/chopp/novo/', qtd='10', preco='450,00', extra=None):
        dados = {'cliente_codigo': '000101', 'cliente_loja': '01', 'cliente_razao_social': 'BAR DO ZE LTDA',
                 'cliente_nome_fantasia': 'Bar do Zé', 'cliente_cpf_cnpj': '12345678000190',
                 'recebimento': 'RETIRADA_LOGISTICA', 'prazo_pagamento': '28 DIAS', 'observacao': '',
                 'item_codigo_1': '000210', 'item_nome_1': 'BARRIL PILSEN 30L', 'item_qtd_1': qtd, 'item_preco_1': preco}
        dados.update(extra or {})
        return client.post(url, dados)

    def test_vendedor_lanca_com_preco_dele(self):
        self.post_chopp(self.cv)
        p = SolicitacaoChopp.objects.get()
        item = p.itens.get()
        self.assertEqual((p.status, p.vendedor, item.quantidade, item.preco_unitario), ('PENDENTE', self.vend, 10, Decimal('450.00')))
        self.assertEqual((item.qtd_solicitada, item.preco_solicitado), (10, Decimal('450.00')))

    def test_validacoes(self):
        self.post_chopp(self.cv, preco='0')
        self.post_chopp(self.cv, qtd='0')
        self.post_chopp(self.cv, extra={'recebimento': 'ENTREGA', 'data_entrega': ''})
        self.post_chopp(self.cv, extra={'prazo_pagamento': ''})
        self.post_chopp(self.cv, extra={'prazo_pagamento': '30 DIAS'})
        self.post_chopp(self.cv, extra={'cliente_codigo': ''})
        self.assertEqual(SolicitacaoChopp.objects.count(), 0)
        amanha = (date.today() + timedelta(days=1)).isoformat()
        self.post_chopp(self.cv, extra={'recebimento': 'ENTREGA', 'data_entrega': amanha})
        self.assertEqual(SolicitacaoChopp.objects.get().data_entrega.isoformat(), amanha)

    def test_janela_do_vendedor_dia_util_anterior(self):
        from django.utils import timezone
        from solicitacoes.chopp import inicio_janela_vendedor
        tz = timezone.get_current_timezone()
        segunda = timezone.make_aware(datetime(2026, 10, 19, 10, 0), tz)
        quarta = timezone.make_aware(datetime(2026, 10, 21, 10, 0), tz)
        self.assertEqual(timezone.localtime(inicio_janela_vendedor(segunda)).date(), date(2026, 10, 16))  # sexta
        self.assertEqual(timezone.localtime(inicio_janela_vendedor(quarta)).date(), date(2026, 10, 20))   # terça

    def test_vendedor_ve_so_os_seus_de_ontem_e_hoje(self):
        from solicitacoes.chopp import inicio_janela_vendedor
        self.post_chopp(self.cv)
        self.post_chopp(self.cv2)
        antigo = SolicitacaoChopp.objects.create(vendedor=self.vend, cliente_codigo='1', cliente_loja='01', cliente_razao_social='ANTIGO',
                                                 cliente_cpf_cnpj='1', recebimento='ENTREGA', prazo_pagamento='7 DIAS')
        SolicitacaoChopp.objects.filter(pk=antigo.pk).update(data_solicitacao=inicio_janela_vendedor() - timedelta(minutes=1))
        r = self.cv.get('/solicitacoes/chopp/')
        self.assertEqual([p.vendedor_id for p in r.context['pedidos']], [self.vend.id])
        self.assertNotContains(r, 'ANTIGO')
        r = self.cg.get('/solicitacoes/chopp/')
        self.assertEqual(len(r.context['pedidos']), 3, 'gestão vê todos')
        self.assertEqual(self.cv.get(f'/solicitacoes/chopp/{antigo.pk}/editar/').status_code, 404)

    def test_vendedor_edita_e_cancela_so_o_proprio_pendente(self):
        self.post_chopp(self.cv)
        p = SolicitacaoChopp.objects.get()
        self.assertEqual(self.cv2.get(f'/solicitacoes/chopp/{p.pk}/editar/').status_code, 404)
        self.post_chopp(self.cv, url=f'/solicitacoes/chopp/{p.pk}/editar/', qtd='12')
        self.assertEqual(p.itens.get().quantidade, 12)
        self.cv2.post(f'/solicitacoes/chopp/{p.pk}/cancelar/', {'motivo': 'x'})
        self.cv.post(f'/solicitacoes/chopp/{p.pk}/cancelar/', {'motivo': ''})
        p.refresh_from_db()
        self.assertEqual(p.status, 'PENDENTE')
        self.cv.post(f'/solicitacoes/chopp/{p.pk}/cancelar/', {'motivo': 'cliente desistiu'})
        p.refresh_from_db()
        self.assertEqual((p.status, p.cancelado_por), ('CANCELADO', self.vend))

    def test_faturamento_corrige_e_finaliza(self):
        self.post_chopp(self.cv)
        p = SolicitacaoChopp.objects.get()
        item = p.itens.get()
        url = f'/solicitacoes/chopp/{p.pk}/processar/'
        self.assertEqual(self.cg.get(url).status_code, 302, 'só o Faturamento processa')
        self.post_chopp(self.cf, url=url, qtd='7', extra={'item_id_1': str(item.id), 'acao': 'finalizar', 'pedido_protheus': ''})
        p.refresh_from_db()
        self.assertEqual(p.status, 'PENDENTE', 'sem número do pedido não finaliza')
        self.post_chopp(self.cf, url=url, qtd='7', extra={'item_id_1': str(item.id), 'acao': 'finalizar', 'pedido_protheus': '028556'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'PENDENTE', 'alterou sem justificar não finaliza')
        self.post_chopp(self.cf, url=url, qtd='7', extra={'item_id_1': str(item.id), 'acao': 'finalizar', 'pedido_protheus': '0285567',
                                                          'observacao_faturamento': 'x'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'PENDENTE', 'pedido Protheus com mais de 6 caracteres não finaliza')
        self.post_chopp(self.cf, url=url, qtd='7', extra={'item_id_1': str(item.id), 'acao': 'finalizar', 'pedido_protheus': '028556',
                                                          'observacao_faturamento': 'cliente levou só 7'})
        p.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((p.status, p.pedido_protheus, p.alterado_pelo_faturamento, p.usuario_faturamento), ('FINALIZADO', '028556', True, self.fat))
        self.assertEqual((item.quantidade, item.qtd_solicitada, item.valor_total), (7, 10, Decimal('3150.00')))
        self.post_chopp(self.cv, url=f'/solicitacoes/chopp/{p.pk}/editar/', qtd='1')
        item.refresh_from_db()
        self.assertEqual(item.quantidade, 7, 'pedido finalizado não pode ser editado')
        self.assertEqual(p.observacao_faturamento, 'cliente levou só 7')

    def test_faturamento_so_altera_prazo_e_itens(self):
        self.post_chopp(self.cv, extra={'observacao': 'entregar cedo'})
        p = SolicitacaoChopp.objects.get()
        self.assertEqual(p.prazo_pagamento_solicitado, '28 DIAS')
        item = p.itens.get()
        url = f'/solicitacoes/chopp/{p.pk}/processar/'
        # tenta mudar cliente, recebimento e observação do vendedor; muda o prazo, remove o item original e inclui outro
        self.post_chopp(self.cf, url=url, extra={
            'cliente_razao_social': 'OUTRO CLIENTE', 'cliente_codigo': '999', 'recebimento': 'ENTREGA', 'observacao': 'mudou',
            'prazo_pagamento': '7 DIAS', 'item_id_1': str(item.id), 'item_removido_1': '1', 'item_qtd_1': '0', 'item_preco_1': '',
            'item_codigo_2': '000300', 'item_nome_2': 'BARRIL IPA 30L', 'item_qtd_2': '3', 'item_preco_2': '500',
            'observacao_faturamento': 'trocou para IPA e paga em 7 dias', 'acao': 'finalizar', 'pedido_protheus': '1234'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'FINALIZADO')
        self.assertEqual((p.cliente_razao_social, p.cliente_codigo, p.recebimento, p.observacao),
                         ('BAR DO ZE LTDA', '000101', 'RETIRADA_LOGISTICA', 'entregar cedo'))
        self.assertEqual((p.prazo_pagamento_solicitado, p.prazo_pagamento, p.prazo_foi_alterado), ('28 DIAS', '7 DIAS', True))
        itens = {i.produto_codigo: i for i in p.itens.all()}
        self.assertEqual((itens['000210'].removido, itens['000210'].quantidade, itens['000210'].qtd_solicitada), (True, 0, 10))
        self.assertEqual(itens['000300'].situacao, 'INCLUIDO')
        self.assertEqual(p.total, Decimal('1500.00'))
        self.assertTrue(p.alterado_pelo_faturamento)

    def test_faturamento_sem_alteracao_nao_exige_justificativa(self):
        self.post_chopp(self.cv)
        p = SolicitacaoChopp.objects.get()
        item = p.itens.get()
        self.post_chopp(self.cf, url=f'/solicitacoes/chopp/{p.pk}/processar/',
                        extra={'item_id_1': str(item.id), 'acao': 'finalizar', 'pedido_protheus': '555'})
        p.refresh_from_db()
        self.assertEqual((p.status, p.alterado_pelo_faturamento), ('FINALIZADO', False))

    def test_nao_remove_todos_os_itens(self):
        self.post_chopp(self.cv)
        p = SolicitacaoChopp.objects.get()
        item = p.itens.get()
        self.post_chopp(self.cf, url=f'/solicitacoes/chopp/{p.pk}/processar/',
                        extra={'item_id_1': str(item.id), 'item_removido_1': '1', 'observacao_faturamento': 'x', 'acao': 'salvar'})
        item.refresh_from_db()
        self.assertFalse(item.removido)

    def test_vendedor_nao_edita_depois_que_faturamento_salvou(self):
        self.post_chopp(self.cv)
        p = SolicitacaoChopp.objects.get()
        item = p.itens.get()
        self.post_chopp(self.cf, url=f'/solicitacoes/chopp/{p.pk}/processar/',
                        extra={'item_id_1': str(item.id), 'acao': 'salvar'})
        p.refresh_from_db()
        self.assertEqual((p.status, p.usuario_faturamento), ('PENDENTE', self.fat))
        self.assertEqual(self.cv.get(f'/solicitacoes/chopp/{p.pk}/editar/').status_code, 302)
        self.cv.post(f'/solicitacoes/chopp/{p.pk}/cancelar/', {'motivo': 'x'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'PENDENTE')

    def test_excel_mostra_solicitado_e_final(self):
        import io
        import pandas as pd
        self.post_chopp(self.cv)
        p = SolicitacaoChopp.objects.get()
        item = p.itens.get()
        self.post_chopp(self.cf, url=f'/solicitacoes/chopp/{p.pk}/processar/', extra={
            'prazo_pagamento': 'A VISTA', 'item_id_1': str(item.id), 'item_removido_1': '1',
            'item_codigo_2': '000300', 'item_nome_2': 'BARRIL IPA 30L', 'item_qtd_2': '3', 'item_preco_2': '500',
            'observacao_faturamento': 'troca', 'acao': 'finalizar', 'pedido_protheus': '9'})
        r = self.cf.get('/solicitacoes/chopp/exportar/excel/')
        df = pd.read_excel(io.BytesIO(r.content))
        for col in ['Prazo solicitado', 'Prazo final', 'Situação do item', 'Observação do vendedor', 'Observação do Faturamento']:
            self.assertIn(col, df.columns)
        self.assertEqual(sorted(df['Situação do item']), ['Incluído pelo Faturamento', 'Removido pelo Faturamento'])
        self.assertEqual(set(df['Prazo solicitado']), {'28 DIAS'})
        self.assertEqual(set(df['Prazo final']), {'A VISTA'})

    def test_faturamento_cancela(self):
        self.post_chopp(self.cv)
        p = SolicitacaoChopp.objects.get()
        self.cf.post(f'/solicitacoes/chopp/{p.pk}/cancelar/', {'motivo': 'sem estoque'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'CANCELADO')

    def test_exportar_so_gestores(self):
        self.post_chopp(self.cv)
        self.assertEqual(self.cv.get('/solicitacoes/chopp/exportar/excel/').status_code, 302)
        self.assertEqual(self.cg.get('/solicitacoes/chopp/exportar/excel/').status_code, 200)
        self.assertEqual(self.cf.get('/solicitacoes/chopp/exportar/excel/').status_code, 200)

    def test_busca_de_produto_so_grupos_de_chopp(self):
        from solicitacoes import chopp
        with mock.patch.object(chopp, 'consultar', return_value=[{'colunas': [], 'linhas': [('000210', 'BARRIL', 'CHOPP')]}]) as c:
            r = self.cv.get('/solicitacoes/api/busca-produtos-chopp/?q=barril')
        self.assertEqual(r.json(), [{'codigo': '000210', 'descricao': 'BARRIL', 'grupo_familia': 'CHOPP'}])
        sql, params = c.call_args.args[1], c.call_args.args[2]
        self.assertIn('B1_GRUPO', sql)
        self.assertEqual(params[:6], ['0101', '0019', '0020', '0027', '0028', '0033'])
        self.assertIn('B1_FILIAL = %s', sql)
        self.assertNotIn('DA1', sql, 'não usa tabela de preço')
        self.assertEqual(c.call_args.args[0], {'protheus_ciec': ['SB1010']}, 'só CIEC, tabela SB1010')
