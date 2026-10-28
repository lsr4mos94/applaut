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
from solicitacoes.models import Bonificacao, BonificacaoItem, DiaConfirmadoChopp, Plantao, SolicitacaoChopp, SolicitacaoChoppItem

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
    def test_vendedor_com_outro_grupo_ve_so_as_dele(self):
        joao, cj = self.usuario('joao', 'Vendedores', 'Solicitantes')
        minha, outra = self.bonificacao(vendedor=joao), self.bonificacao(vendedor=self.vend)
        r = cj.get('/solicitacoes/bonificacoes/')
        self.assertContains(r, f'#{minha.id} ')
        self.assertNotContains(r, f'#{outra.id} ', msg_prefix='Solicitantes não dá visão de todos')
        # quem é do Faturamento ou Gestão Comercial continua vendo todas
        self.assertContains(self.cf.get('/solicitacoes/bonificacoes/'), f'#{outra.id} ')
        joao.groups.add(Group.objects.get(name='Faturamento'))
        self.assertContains(cj.get('/solicitacoes/bonificacoes/'), f'#{outra.id} ')

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
        # E-mails de bonificação desativados temporariamente: ao reativar, volte a exigir 1 e-mail aqui
        self.assertEqual(len(mail.outbox), 0, 'e-mails de bonificação estão desativados')

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


@override_settings(CHOPP_ATIVO=True)
class ChoppTests(Base):
    """A tela de Chopp é do Faturamento e das gestões; os pedidos chegam do Agendamento como ENVIADO."""

    def pedido(self, observacao='', status='ENVIADO'):
        p = SolicitacaoChopp.objects.create(
            vendedor=self.vend, cliente_codigo='000101', cliente_loja='01', cliente_razao_social='BAR DO ZE LTDA',
            cliente_nome_fantasia='Bar do Zé', cliente_cpf_cnpj='12345678000190',
            data_retirada=date.today(), hora_retirada=time(10, 0), condicao_pagamento='01',
            condicao_pagamento_descricao='A VISTA', tabela_preco='007', observacao=observacao, status=status)
        SolicitacaoChoppItem.objects.create(solicitacao=p, produto_codigo='000210', produto_descricao='BARRIL PILSEN 30L',
                                            quantidade=10, preco_unitario=Decimal('450.00'),
                                            qtd_solicitada=10, preco_solicitado=Decimal('450.00'), preco_da_tabela=True)
        return p

    def processar(self, p, qtd='10', preco='450,00', extra=None, client=None):
        item = p.itens.order_by('id').first()
        dados = {'item_id_1': str(item.id), 'item_codigo_1': item.produto_codigo,
                 'item_nome_1': item.produto_descricao, 'item_qtd_1': qtd, 'item_preco_1': preco}
        dados.update(extra or {})
        return (client or self.cf).post(f'/solicitacoes/chopp/{p.pk}/processar/', dados)

    def test_inadimplencia_para_o_faturamento(self):
        from django.core.cache import cache
        from solicitacoes import protheus_chopp
        cache.clear()
        enviado = self.pedido()
        finalizado = self.pedido(status='FINALIZADO')
        info = {'titulos': 2, 'valor': Decimal('580.00'), 'vencimento': date.today() - timedelta(days=10)}
        with mock.patch.object(protheus_chopp, 'inadimplencia', return_value={('000101', '01'): info}) as m:
            r = self.cf.get('/solicitacoes/chopp/')
            pedidos = {p.id: p for p in r.context['pedidos']}
            self.assertEqual(pedidos[enviado.id].inadimplencia['titulos'], 2)
            self.assertFalse(hasattr(pedidos[finalizado.id], 'inadimplencia'), 'só nos pedidos que ainda vão ser processados')
            self.assertContains(r, 'Inadimplente')
            cache.clear()
            r = self.cf.get(f'/solicitacoes/chopp/{enviado.id}/processar/')
            self.assertContains(r, 'Cliente inadimplente.')
        self.assertEqual(self.cf.get('/solicitacoes/agendamentos/api/titulos/').status_code, 200, 'Faturamento vê os títulos')
        self.assertEqual(self.cfin.get('/solicitacoes/agendamentos/api/titulos/').status_code, 200)

    def test_agendado_nao_aparece_nem_processa(self):
        p = self.pedido(status='AGENDADO')
        self.assertEqual(len(self.cf.get('/solicitacoes/chopp/').context['pedidos']), 0)
        self.processar(p, extra={'acao': 'finalizar', 'pedido_protheus': '1'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'AGENDADO')

    def test_quem_entra_na_tela(self):
        self.pedido()
        for c in (self.cv, self.cpla, self.ccad):
            self.assertEqual(c.get('/solicitacoes/chopp/').status_code, 302, 'vendedor e outros grupos não entram')
        for c in (self.cg, self.cfin, self.cf):
            r = c.get('/solicitacoes/chopp/')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(len(r.context['pedidos']), 1, 'vê todos os pedidos')

    def test_tela_nao_inclui_pedidos(self):
        from django.urls import NoReverseMatch, reverse
        with self.assertRaises(NoReverseMatch):
            reverse('chopp_novo')
        self.assertEqual(self.cf.get('/solicitacoes/chopp/novo/').status_code, 404)
        self.assertNotContains(self.cf.get('/solicitacoes/chopp/'), 'Novo Pedido')

    def test_exportar_so_gestoes(self):
        self.pedido()
        self.assertEqual(self.cg.get('/solicitacoes/chopp/exportar/excel/').status_code, 200)
        self.assertEqual(self.cfin.get('/solicitacoes/chopp/exportar/excel/').status_code, 200)
        self.assertEqual(self.cf.get('/solicitacoes/chopp/exportar/excel/').status_code, 302)
        self.assertEqual(self.cv.get('/solicitacoes/chopp/exportar/excel/').status_code, 302)

    def test_so_faturamento_processa_e_cancela(self):
        p = self.pedido()
        for c in (self.cg, self.cfin):
            self.processar(p, qtd='7', extra={'acao': 'finalizar', 'pedido_protheus': '1', 'observacao_faturamento': 'x'}, client=c)
            c.post(f'/solicitacoes/chopp/{p.pk}/cancelar/', {'motivo': 'x'})
        p.refresh_from_db()
        self.assertEqual((p.status, p.itens.get().quantidade), ('ENVIADO', 10))
        self.cf.post(f'/solicitacoes/chopp/{p.pk}/cancelar/', {'motivo': ''})
        p.refresh_from_db()
        self.assertEqual(p.status, 'ENVIADO', 'cancelar exige motivo')
        self.cf.post(f'/solicitacoes/chopp/{p.pk}/cancelar/', {'motivo': 'sem estoque'})
        p.refresh_from_db()
        self.assertEqual((p.status, p.cancelado_por), ('CANCELADO', self.fat))

    def test_faturamento_corrige_e_finaliza(self):
        p = self.pedido()
        self.processar(p, qtd='7', extra={'acao': 'finalizar', 'pedido_protheus': ''})
        p.refresh_from_db()
        self.assertEqual(p.status, 'ENVIADO', 'sem número do pedido não finaliza')
        self.processar(p, qtd='7', extra={'acao': 'finalizar', 'pedido_protheus': '028556'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'ENVIADO', 'alterou sem justificar não finaliza')
        self.processar(p, qtd='7', extra={'acao': 'finalizar', 'pedido_protheus': '0285567', 'observacao_faturamento': 'x'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'ENVIADO', 'pedido Protheus com mais de 6 caracteres não finaliza')
        self.processar(p, qtd='7', extra={'acao': 'finalizar', 'pedido_protheus': '028556', 'observacao_faturamento': 'cliente levou só 7'})
        p.refresh_from_db()
        item = p.itens.get()
        self.assertEqual((p.status, p.pedido_protheus, p.alterado_pelo_faturamento, p.usuario_faturamento), ('FINALIZADO', '028556', True, self.fat))
        self.assertEqual((item.quantidade, item.qtd_solicitada, item.valor_total), (7, 10, Decimal('3150.00')))
        self.assertEqual(p.observacao_faturamento, 'cliente levou só 7')
        self.processar(p, qtd='1', extra={'acao': 'salvar', 'observacao_faturamento': 'x'})
        item.refresh_from_db()
        self.assertEqual(item.quantidade, 7, 'pedido finalizado não muda mais')

    def test_faturamento_so_altera_itens(self):
        p = self.pedido(observacao='entregar cedo')
        self.processar(p, extra={
            'cliente_razao_social': 'OUTRO CLIENTE', 'cliente_codigo': '999', 'observacao': 'mudou',
            'condicao_pagamento': '99', 'data_retirada': '2030-01-01',
            'item_removido_1': '1', 'item_qtd_1': '0', 'item_preco_1': '',
            'item_codigo_2': '000300', 'item_nome_2': 'BARRIL IPA 30L', 'item_qtd_2': '3', 'item_preco_2': '500',
            'observacao_faturamento': 'trocou para IPA', 'acao': 'finalizar', 'pedido_protheus': '1234'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'FINALIZADO')
        self.assertEqual((p.cliente_razao_social, p.cliente_codigo, p.observacao, p.condicao_pagamento, p.data_retirada),
                         ('BAR DO ZE LTDA', '000101', 'entregar cedo', '01', date.today()))
        itens = {i.produto_codigo: i for i in p.itens.all()}
        self.assertEqual((itens['000210'].removido, itens['000210'].quantidade, itens['000210'].qtd_solicitada), (True, 0, 10))
        self.assertEqual(itens['000300'].situacao, 'INCLUIDO')
        self.assertEqual(p.total, Decimal('1500.00'))

    def test_faturamento_sem_alteracao_nao_exige_justificativa(self):
        p = self.pedido()
        self.processar(p, extra={'acao': 'finalizar', 'pedido_protheus': '555'})
        p.refresh_from_db()
        self.assertEqual((p.status, p.alterado_pelo_faturamento), ('FINALIZADO', False))

    def test_nao_remove_todos_os_itens(self):
        p = self.pedido()
        self.processar(p, extra={'item_removido_1': '1', 'observacao_faturamento': 'x', 'acao': 'salvar'})
        self.assertFalse(p.itens.get().removido)

    def test_excel_mostra_solicitado_e_final(self):
        import io
        import pandas as pd
        p = self.pedido()
        self.processar(p, extra={
            'item_removido_1': '1',
            'item_codigo_2': '000300', 'item_nome_2': 'BARRIL IPA 30L', 'item_qtd_2': '3', 'item_preco_2': '500',
            'observacao_faturamento': 'troca', 'acao': 'finalizar', 'pedido_protheus': '9'})
        df = pd.read_excel(io.BytesIO(self.cg.get('/solicitacoes/chopp/exportar/excel/').content))
        for col in ['Data da retirada', 'Horário', 'Condição de pagamento', 'Situação do item', 'Observação do vendedor', 'Observação do Faturamento']:
            self.assertIn(col, df.columns)
        self.assertEqual(sorted(df['Situação do item']), ['Incluído pelo Faturamento', 'Removido na retirada/faturamento'])
        self.assertEqual(set(df['Condição de pagamento']), {'01 - A VISTA'})
        self.assertEqual(set(df['Horário']), {'10:00'})

    def test_busca_de_produto_com_preco_da_tabela(self):
        from solicitacoes import protheus_chopp
        with mock.patch.object(protheus_chopp, 'consultar') as c:
            c.side_effect = [
                [{'colunas': [], 'linhas': [('002089', 'BARRIL CHOPP PILSEN 30L', 'CHOPP'), ('000072', 'COPO', 'COPOS')]}],
                [{'colunas': [], 'linhas': [('002089', 177.0), ('002089', 999.0)]}],
            ]
            r = self.cf.get('/solicitacoes/api/busca-produtos-chopp/?q=barril&tabela=007')
        self.assertEqual(r.json(), [
            {'codigo': '002089', 'descricao': 'BARRIL CHOPP PILSEN 30L', 'grupo_familia': 'CHOPP', 'preco': '177.00'},
            {'codigo': '000072', 'descricao': 'COPO', 'grupo_familia': 'COPOS', 'preco': None},
        ], 'repetido: vale a primeira linha (menor R_E_C_N_O_)')
        sql_prod, params_prod = c.call_args_list[0].args[1], c.call_args_list[0].args[2]
        self.assertIn('B1_MSBLQL', sql_prod)
        self.assertEqual(params_prod[:6], ['0101', '0019', '0020', '0027', '0028', '0033'])
        sql_preco, params_preco = c.call_args_list[1].args[1], c.call_args_list[1].args[2]
        self.assertIn('DA1_FILIAL = %s', sql_preco)
        self.assertIn('ORDER BY R_E_C_N_O_', sql_preco)
        self.assertEqual(params_preco[:2], ['0101', '007'])
        self.assertEqual(c.call_args_list[1].args[0], {'protheus_ciec': ['DA1010']})
        self.assertEqual(self.cv.get('/solicitacoes/api/busca-produtos-chopp/?q=barril').status_code, 403)


@override_settings(CHOPP_ATIVO=True)
class AgendamentoBase(Base):
    """Dados e Protheus simulados para os testes do Agendamento."""

    CLIENTE = {'codigo': '49749519', 'loja': '0001', 'nome': 'LORRANE STEPHANIE', 'fantasia': 'LORRANE', 'cnpj': '49749519000100',
               'condicao': '01', 'condicao_descricao': 'A VISTA', 'tabela': '007'}
    PRODUTOS = {'002089': {'codigo': '002089', 'descricao': 'BARRIL CHOPP PILSEN 30L', 'grupo_familia': 'CHOPP'},
                '000072': {'codigo': '000072', 'descricao': 'COPO DESCARTAVEL 300ML', 'grupo_familia': 'COPOS'}}

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        from solicitacoes import agendamento, protheus_chopp
        cache.clear()
        self.inadimplentes = {}
        self.ag_mod = agendamento
        self.cliente_protheus = dict(self.CLIENTE)
        for nome, func in [
            ('cliente', lambda cod, loja: self.cliente_protheus if self.cliente_protheus and cod == self.CLIENTE['codigo'] else None),
            ('produtos_validos', lambda cods: {c: self.PRODUTOS[c] for c in cods if c in self.PRODUTOS}),
            ('precos_tabela', lambda tab, cods: {c: Decimal('177.00') for c in cods if c == '002089'} if tab == '007' else {}),
            ('inadimplencia', lambda pares, limite: {p: dict(v) for p, v in self.inadimplentes.items() if p in set(pares)}),
        ]:
            p = mock.patch.object(protheus_chopp, nome, side_effect=func)
            p.start()
            self.addCleanup(p.stop)
        inicio, self.fim = agendamento.periodo_calendario()
        self.dia = agendamento.hoje() + timedelta(days=1)
        if self.dia.weekday() == 6:
            self.dia += timedelta(days=1)
        self.domingo = agendamento.hoje() + timedelta(days=6 - agendamento.hoje().weekday())
        self.sabado = [d for d in agendamento.dias_calendario() if d.weekday() == 5][0]

    def agendar(self, client=None, url='/solicitacoes/agendamentos/novo/', extra=None):
        """Grava um pedido pelo formulário (sem dia: o vendedor não escolhe; a gestão pode mandar data/hora)."""
        dados = {'cliente_codigo': '49749519', 'cliente_loja': '0001',
                 'item_codigo_1': '002089', 'item_nome_1': 'X', 'item_qtd_1': '3', 'item_preco_1': '1,00',
                 'item_codigo_2': '000072', 'item_nome_2': 'Y', 'item_qtd_2': '2', 'item_preco_2': '15,00',
                 'observacao': 'buscar cedo'}
        dados.update(extra or {})
        return (client or self.cv).post(url, dados)

    def marcar(self, ag, dia, hora='10:00', client=None, acao=None):
        dados = {'data_retirada': dia.isoformat() if dia else '', 'hora_retirada': hora}
        if acao:
            dados['acao'] = acao
        return (client or self.cg).post(f'/solicitacoes/agendamentos/{ag.id}/agendar/', dados)

    def criar(self, dia=None, status=None, vendedor=None, codigo='1', loja='0001', hora=time(9, 0), descricao='BARRIL PILSEN 30L', qtd=3):
        a = SolicitacaoChopp.objects.create(
            vendedor=vendedor or self.vend, cliente_codigo=codigo, cliente_loja=loja, cliente_razao_social='CLIENTE ' + codigo,
            cliente_cpf_cnpj='1', data_retirada=dia, hora_retirada=hora if dia else None, condicao_pagamento='01',
            condicao_pagamento_descricao='A VISTA', status=status or ('AGENDADO' if dia else 'PENDENTE'))
        SolicitacaoChoppItem.objects.create(solicitacao=a, produto_codigo='002089', produto_descricao=descricao,
                                            quantidade=qtd, preco_unitario=Decimal('177'), qtd_solicitada=qtd, preco_solicitado=Decimal('177'))
        return a


class AgendamentoTests(AgendamentoBase):
    """Pedido do vendedor (pendente) e distribuição pelo backoffice."""

    def test_acesso(self):
        for c in (self.cv, self.cg):
            self.assertEqual(c.get('/solicitacoes/agendamentos/').status_code, 200)
        for c in (self.cf, self.cfin, self.cpla):
            self.assertEqual(c.get('/solicitacoes/agendamentos/').status_code, 302)

    def test_vendedor_grava_pendente_com_dados_do_protheus(self):
        self.agendar(extra={'data_retirada': self.dia.isoformat(), 'hora_retirada': '10:00'})
        ag = SolicitacaoChopp.objects.get()
        self.assertEqual((ag.status, ag.vendedor, ag.data_retirada, ag.hora_retirada), ('PENDENTE', self.vend, None, None),
                         'vendedor não escolhe dia nem hora')
        self.assertEqual((ag.cliente_razao_social, ag.condicao_pagamento, ag.condicao_pagamento_descricao, ag.tabela_preco),
                         ('LORRANE STEPHANIE', '01', 'A VISTA', '007'))
        itens = {i.produto_codigo: i for i in ag.itens.all()}
        barril, copo = itens['002089'], itens['000072']
        self.assertEqual((barril.preco_unitario, barril.preco_da_tabela, barril.produto_descricao), (Decimal('177.00'), True, 'BARRIL CHOPP PILSEN 30L'),
                         'preço da tabela ignora o que veio da tela')
        self.assertEqual((copo.preco_unitario, copo.preco_da_tabela), (Decimal('15.00'), False), 'fora da tabela: preço do vendedor')
        self.assertEqual(ag.total, Decimal('561.00'))
        self.assertEqual((barril.litros, copo.litros, ag.litros), (90, 0, 90), '3 barris de 30L; copo não conta')

    def test_validacoes_do_pedido(self):
        for extra in [{'item_preco_2': ''}, {'item_codigo_2': '999999'}, {'item_qtd_1': '0'}, {'cliente_codigo': '00000000'}]:
            self.agendar(extra=extra)
        self.assertEqual(SolicitacaoChopp.objects.count(), 0)
        self.cliente_protheus['condicao'] = ''
        r = self.agendar()
        self.assertEqual(SolicitacaoChopp.objects.count(), 0)
        self.assertContains(r, 'sem condição de pagamento')

    def test_gestao_agenda_remarca_e_devolve(self):
        ag = self.criar()
        self.marcar(ag, self.dia, '07:10', client=self.cv)
        ag.refresh_from_db()
        self.assertEqual(ag.status, 'PENDENTE', 'vendedor não agenda')
        self.marcar(ag, self.dia, '07:10')
        ag.refresh_from_db()
        self.assertEqual((ag.status, ag.data_retirada, ag.hora_retirada, ag.agendado_por), ('AGENDADO', self.dia, time(7, 10), self.ges),
                         'hora livre (07:10)')
        self.marcar(ag, self.sabado, '15:30')
        ag.refresh_from_db()
        self.assertEqual((ag.data_retirada, ag.hora_retirada), (self.sabado, time(15, 30)), 'remarca, hora livre também no sábado')
        self.marcar(ag, None, '', acao='pendente')
        ag.refresh_from_db()
        self.assertEqual((ag.status, ag.data_retirada, ag.hora_retirada, ag.agendado_por), ('PENDENTE', None, None, None))

    def test_dias_e_horas_invalidos(self):
        ag = self.criar()
        for dia, hora in [(self.domingo, '10:00'), (self.fim + timedelta(days=1), '10:00'),
                          (self.ag_mod.hoje() - timedelta(days=1), '10:00'), (self.dia, ''), (self.dia, '25:00')]:
            self.marcar(ag, dia, hora)
        if self.ag_mod.hoje().weekday() != 6:
            self.marcar(ag, self.ag_mod.hoje(), '00:00')
        ag.refresh_from_db()
        self.assertEqual(ag.status, 'PENDENTE', 'domingo, fora do calendário, passado, hora vazia/ inválida, hora já passada hoje')

    def test_dia_confirmado_entra_como_enviado_e_so_gestao_mexe(self):
        DiaConfirmadoChopp.objects.create(data=self.dia, confirmado_por=self.ges)
        ag = self.criar()
        self.marcar(ag, self.dia, '08:00')
        ag.refresh_from_db()
        self.assertEqual(ag.status, 'ENVIADO', 'dia já confirmado: vai direto para a fábrica')
        # vendedor não altera nem cancela enviado; a gestão altera
        self.agendar(url=f'/solicitacoes/agendamentos/{ag.id}/editar/', extra={'item_qtd_1': '9'})
        self.cv.post(f'/solicitacoes/agendamentos/{ag.id}/cancelar/', {'motivo': 'x'})
        ag.refresh_from_db()
        self.assertEqual((ag.status, ag.itens.count()), ('ENVIADO', 1))
        self.agendar(client=self.cg, url=f'/solicitacoes/agendamentos/{ag.id}/editar/',
                     extra={'data_retirada': self.dia.isoformat(), 'hora_retirada': '08:00', 'item_qtd_1': '9'})
        ag.refresh_from_db()
        self.assertEqual((ag.status, ag.itens.get(produto_codigo='002089').quantidade, ag.vendedor), ('ENVIADO', 9, self.vend),
                         'gestão altera o enviado; vendedor continua o mesmo')

    def test_gestao_inclui_ja_agendado(self):
        self.agendar(client=self.cg, extra={'data_retirada': self.dia.isoformat(), 'hora_retirada': '13:45'})
        ag = SolicitacaoChopp.objects.get()
        self.assertEqual((ag.status, ag.data_retirada, ag.hora_retirada), ('AGENDADO', self.dia, time(13, 45)))
        self.agendar(client=self.cg, extra={'data_retirada': self.dia.isoformat(), 'hora_retirada': ''})
        self.assertEqual(SolicitacaoChopp.objects.count(), 1, 'dia sem hora não grava')
        outro_dia = self.ag_mod.dias_calendario()[3]
        DiaConfirmadoChopp.objects.create(data=outro_dia, confirmado_por=self.ges)
        self.agendar(client=self.cg, extra={'data_retirada': outro_dia.isoformat(), 'hora_retirada': '09:00'})
        self.assertEqual(SolicitacaoChopp.objects.filter(data_retirada=outro_dia).get().status, 'ENVIADO')

    def test_vendedor_edita_pendente_e_agendado_sem_mudar_dia(self):
        ag = self.criar(self.dia, hora=time(10, 0))
        self.agendar(url=f'/solicitacoes/agendamentos/{ag.id}/editar/', extra={'item_qtd_1': '5', 'data_retirada': self.sabado.isoformat()})
        ag.refresh_from_db()
        self.assertEqual((ag.status, ag.data_retirada, ag.hora_retirada, ag.itens.get(produto_codigo='002089').quantidade),
                         ('AGENDADO', self.dia, time(10, 0), 5), 'continua agendado no mesmo dia e hora')
        self.assertEqual(self.cv2.get(f'/solicitacoes/agendamentos/{ag.id}/editar/').status_code, 404)

    def test_calendario_pendentes_dias_e_litros(self):
        meu = self.criar()
        outro = self.criar(vendedor=self.vend2, qtd=2, descricao='BARRIL PILSEN 50L')
        agendado = self.criar(self.dia, qtd=4)
        self.criar(self.dia, status='CANCELADO', qtd=10)
        r = self.cv.get('/solicitacoes/agendamentos/')
        self.assertEqual([a.id for a in r.context['pedidos_pendentes']], [meu.id], 'vendedor vê só os seus pendentes')
        r = self.cg.get('/solicitacoes/agendamentos/')
        self.assertEqual([a.id for a in r.context['pedidos_pendentes']], [meu.id, outro.id])
        self.assertEqual((r.context['litros_pendentes'], r.context['litros_agendados']), (190, 120), '3x30 + 2x50 / 4x30 (cancelado fora)')
        dia = {d['data']: d for d in r.context['dias']}[self.dia]
        self.assertEqual((dia['litros'], [a.id for a in dia['agendamentos']][:1]), (120, [agendado.id]))
        r = self.cg.get(f'/solicitacoes/agendamentos/?vendedor={self.vend2.id}')
        self.assertEqual([a.id for a in r.context['pedidos_pendentes']], [outro.id], 'filtro por vendedor')
        self.assertEqual([d['data'] for d in r.context['dias']], self.ag_mod.dias_calendario())

    def test_cancelar(self):
        pend = self.criar()
        self.cv.post(f'/solicitacoes/agendamentos/{pend.id}/cancelar/', {'motivo': ''})
        pend.refresh_from_db()
        self.assertEqual(pend.status, 'PENDENTE', 'cancelar exige motivo')
        self.cv.post(f'/solicitacoes/agendamentos/{pend.id}/cancelar/', {'motivo': 'cliente desistiu'})
        pend.refresh_from_db()
        self.assertEqual((pend.status, pend.cancelado_por), ('CANCELADO', self.vend))
        env = self.criar(self.dia, status='ENVIADO')
        self.cv.post(f'/solicitacoes/agendamentos/{env.id}/cancelar/', {'motivo': 'x'})
        env.refresh_from_db()
        self.assertEqual(env.status, 'ENVIADO')
        self.cg.post(f'/solicitacoes/agendamentos/{env.id}/cancelar/', {'motivo': 'cliente ligou'})
        env.refresh_from_db()
        self.assertEqual(env.status, 'CANCELADO', 'gestão cancela o enviado')

    def test_calendario_hoje_e_proximos_6_dias(self):
        sexta = date(2026, 10, 23)
        self.assertEqual(self.ag_mod.dias_calendario(sexta),
                         [date(2026, 10, d) for d in (23, 24, 26, 27, 28, 29, 30)], 'pula o domingo 25/10')

    def test_inadimplencia_consulta_a_cada_carregamento(self):
        self.criar(self.dia, codigo='10842635', loja='0645')
        self.inadimplentes = {('10842635', '0645'): {'titulos': 1, 'valor': Decimal('10'), 'vencimento': self.ag_mod.hoje()}}
        from solicitacoes import protheus_chopp
        self.cg.get('/solicitacoes/agendamentos/')
        self.inadimplentes = {}   # cliente pagou
        r = self.cg.get('/solicitacoes/agendamentos/')
        self.assertEqual(protheus_chopp.inadimplencia.call_count, 2, 'sem guardar entre carregamentos')
        dia = {d['data']: d for d in r.context['dias']}[self.dia]
        self.assertIsNone(dia['agendamentos'][0].inadimplencia, 'pagamento aparece na hora')
        self.assertIn('no-cache', r['Cache-Control'], 'navegador não reaproveita a página')
        self.assertIn('no-store', r['Cache-Control'])

    def test_protheus_fora_do_ar_nao_grava(self):
        from app.protheus import ProtheusIndisponivel
        with mock.patch.object(self.ag_mod.protheus_chopp, 'cliente', side_effect=ProtheusIndisponivel('x')):
            r = self.agendar()
        self.assertContains(r, 'Não foi possível consultar o Protheus')
        self.assertEqual(SolicitacaoChopp.objects.count(), 0)

    def test_busca_de_clientes_filtra_ativos_e_filial(self):
        from solicitacoes import protheus_chopp
        with mock.patch.object(protheus_chopp, 'consultar', return_value=[{'colunas': ['A1_COD', 'A1_LOJA', 'A1_NOME', 'A1_NREDUZ', 'A1_CGC', 'A1_COND', 'A1_TABELA', 'E4_DESCRI'],
                                                                         'linhas': [('49749519', '0001', 'LORRANE ', 'LO', '1', '01', '007', 'A VISTA ')]}]) as c:
            r = self.cv.get('/solicitacoes/agendamentos/api/clientes/?q=lorrane')
        self.assertEqual(r.json()[0]['condicao_descricao'], 'A VISTA')
        sql, params = c.call_args.args[1], c.call_args.args[2]
        self.assertIn("A1_MSBLQL <> '1'", sql)
        self.assertIn('SA1.A1_FILIAL = %s', sql)
        self.assertIn('SE4.E4_FILIAL = SA1.A1_FILIAL', sql)
        self.assertEqual(params[0], '0101')
        self.assertEqual(c.call_args.args[0], {'protheus_ciec': ['SA1010']})


class ConfirmacaoDiaTests(AgendamentoBase):
    """Etapa 2: confirmação do dia pela Gestão Comercial."""

    def setUp(self):
        super().setUp()
        self.proximo = self.ag_mod.proximo_dia_util()

    def criar(self, dia, vendedor=None, status='AGENDADO'):
        return SolicitacaoChopp.objects.create(
            vendedor=vendedor or self.vend, cliente_codigo='1', cliente_loja='0001', cliente_razao_social='X', cliente_cpf_cnpj='1',
            data_retirada=dia, hora_retirada=time(9, 0), condicao_pagamento='01', condicao_pagamento_descricao='A VISTA', status=status)

    def confirmar(self, dia, client=None):
        return (client or self.cg).post(f'/solicitacoes/agendamentos/confirmar/{dia.isoformat()}/')

    def test_proximo_dia_util(self):
        sexta, sabado = date(2026, 10, 23), date(2026, 10, 24)
        self.assertEqual(self.ag_mod.proximo_dia_util(sexta), sabado)
        self.assertEqual(self.ag_mod.proximo_dia_util(sabado), date(2026, 10, 26), 'sábado confirma a segunda')

    def test_confirma_envia_e_trava(self):
        a1, a2 = self.criar(self.proximo), self.criar(self.proximo, vendedor=self.vend2)
        cancelado = self.criar(self.proximo, status='CANCELADO')
        outro_dia = self.criar(self.proximo + timedelta(days=1 if self.proximo.weekday() != 5 else 2))
        self.confirmar(self.proximo, client=self.cv)
        self.confirmar(self.proximo, client=self.cf)
        self.assertEqual(SolicitacaoChopp.objects.filter(status='ENVIADO').count(), 0, 'só a Gestão Comercial confirma')
        self.confirmar(self.proximo)
        for a, st in [(a1, 'ENVIADO'), (a2, 'ENVIADO'), (cancelado, 'CANCELADO'), (outro_dia, 'AGENDADO')]:
            a.refresh_from_db()
            self.assertEqual(a.status, st)
        conf = DiaConfirmadoChopp.objects.get()
        self.assertEqual((conf.data, conf.confirmado_por), (self.proximo, self.ges))
        # aparece para o Faturamento
        self.assertEqual({p.id for p in self.cf.get('/solicitacoes/chopp/').context['pedidos']}, {a1.id, a2.id, cancelado.id})
        # dia travado: não inclui, não edita, não cancela
        self.dia = self.proximo
        self.agendar()
        self.assertEqual(SolicitacaoChopp.objects.filter(data_retirada=self.proximo).count(), 3)
        self.cv.post(f'/solicitacoes/agendamentos/{a1.id}/cancelar/', {'motivo': 'x'})
        a1.refresh_from_db()
        self.assertEqual(a1.status, 'ENVIADO')
        # mover outro agendamento para o dia confirmado também não pode
        self.agendar(url=f'/solicitacoes/agendamentos/{outro_dia.id}/editar/', extra={'data_retirada': self.proximo.isoformat()})
        outro_dia.refresh_from_db()
        self.assertNotEqual(outro_dia.data_retirada, self.proximo)

    def test_nao_confirma_dia_futuro_nem_sem_pendentes(self):
        depois = self.proximo + timedelta(days=1 if self.proximo.weekday() != 5 else 2)
        futuro = self.criar(depois)
        self.confirmar(depois)
        futuro.refresh_from_db()
        self.assertEqual(futuro.status, 'AGENDADO', 'só até o próximo dia útil')
        self.confirmar(self.proximo)
        self.assertFalse(DiaConfirmadoChopp.objects.exists(), 'sem pendentes não confirma')

    def test_confirma_dia_atrasado(self):
        ontem = self.ag_mod.hoje() - timedelta(days=1)
        atrasado = self.criar(ontem)
        r = self.cg.get('/solicitacoes/agendamentos/')
        self.assertEqual([d['data'] for d in r.context['atrasados']], [ontem], 'aviso de dia anterior sem confirmar')
        self.assertTrue(r.context['atrasados'][0]['pode_confirmar'])
        self.assertEqual(self.cv.get('/solicitacoes/agendamentos/').context['atrasados'], [], 'vendedor não vê o aviso')
        self.confirmar(ontem)
        atrasado.refresh_from_db()
        self.assertEqual(atrasado.status, 'ENVIADO')

    def test_botao_so_para_gestao_e_dia_certo(self):
        self.criar(self.proximo)
        semana = ''
        dias = {d['data']: d for d in self.cg.get('/solicitacoes/agendamentos/' + semana).context['dias']}
        self.assertTrue(dias[self.proximo]['pode_confirmar'])
        self.assertFalse(any(d['pode_confirmar'] for d in self.cv.get('/solicitacoes/agendamentos/' + semana).context['dias']))
        self.confirmar(self.proximo)
        dias = {d['data']: d for d in self.cg.get('/solicitacoes/agendamentos/' + semana).context['dias']}
        self.assertFalse(dias[self.proximo]['pode_confirmar'])
        self.assertTrue(dias[self.proximo]['pode_incluir'], 'gestão ainda inclui no dia confirmado')
        self.assertFalse(any(d['pode_incluir'] for d in self.cv.get('/solicitacoes/agendamentos/').context['dias']), 'vendedor não escolhe dia')
        self.assertIsNotNone(dias[self.proximo]['confirmado'])


class InadimplenciaEPdfTests(AgendamentoBase):
    """Etapa 3: alerta de inadimplência e PDF do dia confirmado."""

    def criar(self, dia, codigo='1', loja='0001', status='AGENDADO', vendedor=None):
        a = SolicitacaoChopp.objects.create(
            vendedor=vendedor or self.vend, cliente_codigo=codigo, cliente_loja=loja, cliente_razao_social='CLIENTE ' + codigo,
            cliente_cpf_cnpj='1', data_retirada=dia, hora_retirada=time(9, 0), condicao_pagamento='01',
            condicao_pagamento_descricao='A VISTA', status=status)
        SolicitacaoChoppItem.objects.create(solicitacao=a, produto_codigo='002089', produto_descricao='BARRIL PILSEN 30L',
                                            quantidade=3, preco_unitario=Decimal('177'), qtd_solicitada=3, preco_solicitado=Decimal('177'))
        return a

    def semana(self, dia):
        return ''

    def test_alerta_no_calendario_e_no_formulario(self):
        dia = self.dia
        inad = self.criar(dia, codigo='10842635', loja='0645')
        ok = self.criar(dia, codigo='2')
        self.inadimplentes = {('10842635', '0645'): {'titulos': 2, 'valor': Decimal('580.00'), 'vencimento': self.ag_mod.hoje() - timedelta(days=37)}}
        r = self.cg.get('/solicitacoes/agendamentos/' + self.semana(dia))
        cards = {a.id: a for d in r.context['dias'] for a in d['agendamentos']}
        self.assertEqual(cards[inad.id].inadimplencia['dias'], 37)
        self.assertIsNone(cards[ok.id].inadimplencia)
        self.assertContains(r, 'Inadimplente')
        j = self.cv.get('/solicitacoes/agendamentos/api/inadimplencia/?codigo=10842635&loja=0645').json()
        self.assertEqual((j['inadimplente'], j['titulos'], j['valor'], j['dias']), (True, 2, '580.00', 37))
        self.assertFalse(self.cv.get('/solicitacoes/agendamentos/api/inadimplencia/?codigo=2&loja=0001').json()['inadimplente'])
        # só alerta: agendar para cliente inadimplente continua permitido
        self.inadimplentes[('49749519', '0001')] = {'titulos': 1, 'valor': Decimal('10'), 'vencimento': self.ag_mod.hoje()}
        self.agendar()
        self.assertTrue(SolicitacaoChopp.objects.filter(cliente_codigo='49749519').exists())

    def test_api_de_titulos(self):
        titulos = [{'empresa': 'CIEC 01', 'filial': '0101', 'prefixo': '1', 'numero': '000105137', 'parcela': '', 'tipo': 'NF',
                    'emissao': date(2026, 8, 28), 'vencimento': self.ag_mod.hoje() - timedelta(days=37),
                    'valor': Decimal('355.00'), 'saldo': Decimal('300.00')}]
        with mock.patch.object(self.ag_mod.protheus_chopp, 'titulos_vencidos', return_value=titulos) as m:
            j = self.cv.get('/solicitacoes/agendamentos/api/titulos/?codigo=10842635&loja=645').json()
        self.assertEqual(j[0]['titulo'], '1-000105137')
        self.assertEqual((j[0]['dias'], j[0]['saldo'], j[0]['valor'], j[0]['empresa']), (37, '300.00', '355.00', 'CIEC 01'))
        self.assertEqual(m.call_args.args[:2], ('10842635', '645'))
        self.assertEqual(self.cpla.get('/solicitacoes/agendamentos/api/titulos/?codigo=1&loja=1').status_code, 403)

    @override_settings(INADIMPLENCIA_VALOR_MINIMO=5)
    def test_valor_minimo(self):
        self.inadimplentes = {('1', '0001'): {'titulos': 1, 'valor': Decimal('1.04'), 'vencimento': self.ag_mod.hoje()}}
        self.assertFalse(self.cv.get('/solicitacoes/agendamentos/api/inadimplencia/?codigo=1&loja=0001').json()['inadimplente'])

    def test_protheus_fora_nao_quebra_o_calendario(self):
        from app.protheus import ProtheusIndisponivel
        self.criar(self.dia)
        with mock.patch.object(self.ag_mod.protheus_chopp, 'inadimplencia', side_effect=ProtheusIndisponivel('x')):
            r = self.cg.get('/solicitacoes/agendamentos/' + self.semana(self.dia))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['inadimplencia_indisponivel'])

    def test_pdf_do_dia_confirmado(self):
        proximo = self.ag_mod.proximo_dia_util()
        self.criar(proximo, codigo='A')
        b = self.criar(proximo, codigo='B', vendedor=self.vend2)
        self.criar(proximo, codigo='C', status='CANCELADO')
        url = f'/solicitacoes/agendamentos/pdf/{proximo.isoformat()}/'
        self.assertEqual(self.cg.get(url).status_code, 302, 'dia ainda não confirmado')
        self.cg.post(f'/solicitacoes/agendamentos/confirmar/{proximo.isoformat()}/')
        r = self.cg.get('/solicitacoes/agendamentos/' + self.semana(proximo))
        self.assertEqual(r.context['pdf_dia'], proximo.isoformat(), 'abre o PDF logo depois de confirmar')
        self.assertIsNone(self.cg.get('/solicitacoes/agendamentos/' + self.semana(proximo)).context['pdf_dia'], 'só uma vez')
        # Faturamento mexe depois: o PDF continua com o que foi agendado
        item_b = b.itens.get()
        item_b.quantidade = 1
        item_b.save()
        r = self.cg.get(url)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertEqual([a.cliente_codigo for a in r.context['retiradas']], ['A', 'B'], 'cancelado não vai para a fábrica')
        self.assertEqual(r.context['totais'], [{'codigo': '002089', 'descricao': 'BARRIL PILSEN 30L', 'quantidade': 6}])
        from django.template.loader import render_to_string
        html = render_to_string('solicitacoes/agendamento_pdf.html', r.context.flatten())
        self.assertNotIn('R$', html, 'sem preço')
        self.assertIn('Total de unidades', html)
        self.assertEqual(self.cv.get(url).status_code, 302, 'só a Gestão Comercial')


class FabricaTests(AgendamentoBase):
    """Tela da Fábrica: pedidos de hoje já enviados; marca entregue ou não retirou."""

    def setUp(self):
        super().setUp()
        self.fab, self.cfab = self.usuario('fab', 'Fábrica')
        self.hoje = self.ag_mod.hoje()

    def test_so_a_fabrica_e_so_hoje_enviados(self):
        hoje_env = self.criar(self.hoje, status='ENVIADO')
        self.criar(self.hoje, status='AGENDADO')
        self.criar(self.dia, status='ENVIADO')
        self.criar(self.hoje, status='CANCELADO')
        for c in (self.cv, self.cg, self.cf):
            self.assertEqual(c.get('/solicitacoes/fabrica/').status_code, 302)
        r = self.cfab.get('/solicitacoes/fabrica/')
        self.assertEqual([p.id for p in r.context['pedidos']], [hoje_env.id])
        self.assertNotContains(r, 'R$', msg_prefix='sem preços')
        self.assertEqual(self.cfab.get('/solicitacoes/agendamentos/').status_code, 302, 'fábrica não vê o calendário')

    def test_usuario_so_da_fabrica_entra_direto_e_sem_menu(self):
        self.assertRedirects(self.cfab.get('/'), '/solicitacoes/fabrica/')
        r = self.cfab.get('/solicitacoes/fabrica/')
        self.assertNotContains(r, 'id="menuPrincipal"', msg_prefix='sem menu')
        self.assertContains(r, 'Sair')
        # outros grupos continuam com o menu e a tela inicial
        self.assertEqual(self.cg.get('/').status_code, 200)
        self.fab.groups.add(Group.objects.get_or_create(name='Faturamento')[0])
        self.assertEqual(self.cfab.get('/').status_code, 200, 'quem tem outro grupo vê a tela inicial')
        self.assertContains(self.cfab.get('/solicitacoes/fabrica/'), 'id="menuPrincipal"')

    def test_marca_entregue_com_ajustes(self):
        ped = self.criar(self.hoje, status='ENVIADO', qtd=3)
        item = ped.itens.get()
        self.cfab.post(f'/solicitacoes/fabrica/{ped.id}/entregar/', {f'qtd_{item.id}': '2', 'novo_codigo_1': '000072', 'novo_qtd_1': '5'})
        ped.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((ped.status, ped.entregue_por), ('ENTREGUE', self.fab))
        self.assertEqual((item.quantidade, item.qtd_solicitada), (2, 3), 'guarda o que foi pedido e o que saiu')
        copo = ped.itens.get(produto_codigo='000072')
        self.assertEqual((copo.quantidade, copo.incluido_por, copo.preco_unitario, copo.situacao_display),
                         (5, 'FABRICA', Decimal('0'), 'Incluído pela Fábrica'), 'fora da tabela: Faturamento informa o preço')
        # Faturamento processa o entregue; ajustes da fábrica não exigem justificativa do Faturamento
        r = self.cf.get('/solicitacoes/chopp/')
        self.assertIn(ped.id, [p.id for p in r.context['pedidos']])
        dados = {'item_id_1': str(item.id), 'item_codigo_1': '002089', 'item_nome_1': 'X', 'item_qtd_1': '2', 'item_preco_1': '177',
                 'item_id_2': str(copo.id), 'item_codigo_2': '000072', 'item_nome_2': 'Y', 'item_qtd_2': '5', 'item_preco_2': '15',
                 'acao': 'finalizar', 'pedido_protheus': '123'}
        self.cf.post(f'/solicitacoes/chopp/{ped.id}/processar/', dados)
        ped.refresh_from_db()
        self.assertEqual(ped.status, 'ENTREGUE', 'mudou o preço do copo: precisa justificar')
        dados['observacao_faturamento'] = 'preço do copo'
        self.cf.post(f'/solicitacoes/chopp/{ped.id}/processar/', dados)
        ped.refresh_from_db()
        self.assertEqual(ped.status, 'FINALIZADO')

    def test_faturamento_sem_mexer_nao_justifica_ajuste_da_fabrica(self):
        ped = self.criar(self.hoje, status='ENVIADO', qtd=3)
        item = ped.itens.get()
        self.cfab.post(f'/solicitacoes/fabrica/{ped.id}/entregar/', {f'qtd_{item.id}': '1'})
        self.cf.post(f'/solicitacoes/chopp/{ped.id}/processar/', {
            'item_id_1': str(item.id), 'item_codigo_1': '002089', 'item_nome_1': 'X', 'item_qtd_1': '1', 'item_preco_1': '177',
            'acao': 'finalizar', 'pedido_protheus': '9'})
        ped.refresh_from_db()
        self.assertEqual((ped.status, ped.alterado_pelo_faturamento), ('FINALIZADO', False))

    def test_nao_retirou_e_validacoes(self):
        ped = self.criar(self.hoje, status='ENVIADO')
        item = ped.itens.get()
        self.cfab.post(f'/solicitacoes/fabrica/{ped.id}/entregar/', {f'qtd_{item.id}': '0'})
        ped.refresh_from_db()
        self.assertEqual(ped.status, 'ENVIADO', 'tudo zerado: tem que usar "não retirou"')
        self.cfab.post(f'/solicitacoes/fabrica/{ped.id}/nao-retirou/', {'motivo': 'não apareceu'})
        ped.refresh_from_db()
        self.assertEqual((ped.status, ped.cancelado_por, ped.motivo_cancelamento), ('CANCELADO', self.fab, 'Cliente não retirou: não apareceu'))
        self.assertIn(ped.id, [p.id for p in self.cfab.get('/solicitacoes/fabrica/').context['pedidos']], 'continua na lista do dia')
        amanha = self.criar(self.dia, status='ENVIADO')
        self.cfab.post(f'/solicitacoes/fabrica/{amanha.id}/nao-retirou/', {})
        amanha.refresh_from_db()
        self.assertEqual(amanha.status, 'ENVIADO', 'só pedidos de hoje')


class InadimplenciaProtheusTests(Base):
    """Consulta de títulos vencidos (SE1) usada no alerta do Agendamento."""

    def test_consulta_de_titulos_no_protheus(self):
        from solicitacoes import protheus_chopp
        with mock.patch.object(protheus_chopp, 'consultar', return_value=[
            {'colunas': [], 'linhas': [('10842635', '645', 2, 580.0, '20260915'), ('10842635', '999', 1, 50.0, '20260101')]},
            {'colunas': [], 'linhas': [('10842635', '645', 1, 1.04, '20260626')]},
        ]) as c:
            r = protheus_chopp.inadimplencia([('10842635', '645')], date(2026, 10, 22))
        self.assertEqual(r, {('10842635', '645'): {'titulos': 3, 'valor': Decimal('581.04'), 'vencimento': date(2026, 6, 26)}},
                         'soma as empresas, só a loja do agendamento, vencimento mais antigo')
        bases, sql, params = c.call_args.args
        self.assertEqual(bases, {'protheus_ciec': ['SE1010', 'SE1020'], 'protheus_wrp': ['SE1010']})
        self.assertIn("E1_TIPO NOT IN ('RA', 'NCC')", sql)
        self.assertIn('E1_SALDO > 0', sql)
        self.assertEqual(params[:3], ['20261022', '%-', '10842635'])

    def test_titulos_vencidos_do_cliente(self):
        from solicitacoes import protheus_chopp
        colunas = ['E1_FILIAL', 'E1_PREFIXO', 'E1_NUM', 'E1_PARCELA', 'E1_TIPO', 'E1_EMISSAO', 'E1_VENCREA', 'E1_VALOR', 'E1_SALDO']
        with mock.patch.object(protheus_chopp, 'consultar', return_value=[
            {'base': 'protheus_ciec', 'tabela': 'SE1010', 'colunas': colunas,
             'linhas': [('0101', '1  ', '000105137', ' ', 'NF ', '20260828', '20260915', 355.0, 355.0)]},
            {'base': 'protheus_ciec', 'tabela': 'SE1020', 'colunas': colunas,
             'linhas': [('0101', 'I', '000777', '', 'NF', '20260801', '20260810', 50.0, 50.0)]},
            {'base': 'protheus_wrp', 'tabela': 'SE1010', 'colunas': colunas,
             'linhas': [('0101', 'R', '000012', 'A', 'NF', '20260612', '20260626', 10.0, 1.04)]},
        ]) as c:
            titulos = protheus_chopp.titulos_vencidos('10842635', '645', date(2026, 10, 22))
        self.assertEqual([(t['empresa'], t['numero'], t['vencimento'], t['saldo']) for t in titulos], [
            ('WRP', '000012', date(2026, 6, 26), Decimal('1.04')),
            ('ISLA', '000777', date(2026, 8, 10), Decimal('50.00')),
            ('CIEC', '000105137', date(2026, 9, 15), Decimal('355.00')),
        ], 'do mais antigo ao mais novo, com a empresa de cada título')
        self.assertEqual(c.call_args.args[2], ['20261022', '%-', '10842635', '645'])
        self.assertIn('RTRIM(E1_LOJA) = %s', c.call_args.args[1])


class PopularAgendamentosTesteTests(Base):
    """Comando que gera dados de teste do Agendamento."""

    def rodar(self, *args):
        from io import StringIO
        from django.core.management import call_command
        from solicitacoes import protheus_chopp
        clientes = [{'codigo': f'0000{i}', 'loja': '0001', 'nome': f'CLIENTE {i}', 'fantasia': f'Cliente {i}', 'cnpj': '1',
                     'condicao': '01', 'condicao_descricao': 'A VISTA', 'tabela': '007'} for i in range(5)]
        produtos = [{'codigo': '002089', 'descricao': 'BARRIL CHOPP PILSEN 30L', 'grupo_familia': 'X'},
                    {'codigo': '000072', 'descricao': 'COPO DESCARTAVEL', 'grupo_familia': 'Y'}]
        with mock.patch.object(protheus_chopp, 'clientes_ao_acaso', return_value=clientes), \
             mock.patch.object(protheus_chopp, 'listar_produtos', return_value=produtos), \
             mock.patch.object(protheus_chopp, 'precos_tabela', return_value={'002089': Decimal('177.00'), '000072': Decimal('15.00')}):
            saida = StringIO()
            call_command('popular_agendamentos_teste', *args, stdout=saida)
            return saida.getvalue()

    @override_settings(DEBUG=True)
    def test_cria_e_limpa(self):
        from solicitacoes import agendamento
        manual = SolicitacaoChopp.objects.create(
            vendedor=self.vend, cliente_codigo='9', cliente_loja='1', cliente_razao_social='REAL', cliente_cpf_cnpj='1',
            data_retirada=agendamento.hoje(), hora_retirada=time(8, 0), condicao_pagamento='01', condicao_pagamento_descricao='A VISTA')
        self.rodar()
        testes = SolicitacaoChopp.objects.filter(observacao__startswith='[TESTE]')
        self.assertGreater(testes.count(), 10)
        hoje = agendamento.hoje()
        self.assertFalse(testes.filter(data_retirada__lte=hoje, status='AGENDADO').exists(), 'dias até hoje ficam confirmados')
        self.assertFalse(testes.filter(data_retirada__gt=hoje, status__in=['ENVIADO', 'FINALIZADO']).exists())
        self.assertFalse(testes.filter(data_retirada__week_day=1).exists(), 'sem domingo')
        for a in testes:
            self.assertEqual(a.hora_retirada is None, a.status == 'PENDENTE')
            self.assertTrue(a.itens.exists())
        self.assertTrue(DiaConfirmadoChopp.objects.filter(data=hoje).exists() or hoje.weekday() == 6)
        self.rodar('--limpar')
        self.assertFalse(SolicitacaoChopp.objects.filter(observacao__startswith='[TESTE]').exists())
        self.assertTrue(SolicitacaoChopp.objects.filter(pk=manual.pk).exists(), 'não apaga o que não é de teste')

    @override_settings(DEBUG=True)
    def test_limpar_tudo(self):
        from solicitacoes import agendamento
        SolicitacaoChopp.objects.create(
            vendedor=self.vend, cliente_codigo='9', cliente_loja='1', cliente_razao_social='REAL', cliente_cpf_cnpj='1',
            condicao_pagamento='01', condicao_pagamento_descricao='A VISTA')
        DiaConfirmadoChopp.objects.create(data=agendamento.hoje(), confirmado_por=self.ges)
        self.rodar()
        self.rodar('--limpar', '--tudo')
        self.assertEqual((SolicitacaoChopp.objects.count(), SolicitacaoChoppItem.objects.count(), DiaConfirmadoChopp.objects.count()), (0, 0, 0))

    @override_settings(DEBUG=False)
    def test_nao_roda_em_producao(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.rodar()


@override_settings(CHOPP_ATIVO=False)
class ChoppOcultoTests(Base):
    """Em produção, enquanto CHOPP_ATIVO=False: Agendamento, Chopp e Fábrica somem para todos (menos o superusuário)."""

    def test_telas_e_menus_ocultos(self):
        fab, cfab = self.usuario('fab', 'Fábrica')
        for c, url in ((self.cg, '/solicitacoes/agendamentos/'), (self.cv, '/solicitacoes/agendamentos/'),
                       (self.cf, '/solicitacoes/chopp/'), (cfab, '/solicitacoes/fabrica/'),
                       (self.cg, '/solicitacoes/agendamentos/api/clientes/?q=abc')):
            self.assertEqual(c.get(url).status_code, 404, url)
        for c in (self.cg, self.cf, self.cv):
            r = c.get('/')
            self.assertNotContains(r, '/solicitacoes/agendamentos/')
            self.assertNotContains(r, '/solicitacoes/chopp/')
        self.assertEqual(cfab.get('/').status_code, 200, 'fábrica não é jogada para uma tela oculta')
        self.assertContains(self.cg.get('/'), '/solicitacoes/bonificacoes/', msg_prefix='o resto continua')

    def test_superusuario_ve_para_validar(self):
        adm = User.objects.create_superuser('adm', 'adm@teste.com', 'x')
        c = Client()
        c.force_login(adm)
        self.assertEqual(c.get('/solicitacoes/chopp/').status_code, 200)
        self.assertEqual(c.get('/solicitacoes/agendamentos/').status_code, 200)
        # superusuário que também está num grupo vê o menu
        adm.groups.add(Group.objects.get(name='Gestão Comercial'))
        self.assertContains(c.get('/'), '/solicitacoes/agendamentos/')
