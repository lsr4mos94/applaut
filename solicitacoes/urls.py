from django.urls import path
from . import views
from app.permissoes import requer_chopp
from . import agendamento, chopp, fabrica

urlpatterns = [
    path('boletos/', views.buscar_boleto, name='buscar_boleto'),
    path('boletos/baixar/<str:caminho_b64>/', views.baixar_boleto, name='baixar_boleto'),

    path('plantoes/', views.plantao_list, name='plantao_list'),
    path('plantoes/novo/', views.novo_plantao, name='novo_plantao'),
    path('plantoes/confirmar/<int:pk>/', views.confirmar_plantao, name='confirmar_plantao'),
    path('plantoes/excluir/<int:pk>/', views.excluir_plantao, name='excluir_plantao'),
    path('plantoes/detalhes/<int:pk>/', views.get_plantao_detalhes, name='detalhes_plantao'),
    path('plantoes/editar/<int:pk>/', views.editar_plantao, name='editar_plantao'),

    path('bonificacoes/', views.bonificacao_list, name='bonificacao_list'),
    path('bonificacoes/nova/', views.criar_bonificacao, name='criar_bonificacao'),
    path('bonificacoes/gerenciar/<int:pk>/<str:acao>/', views.gerenciar_solicitacao, name='gerenciar_solicitacao'),
    path('bonificacao/excluir/<int:pk>/', views.excluir_bonificacao, name='excluir_bonificacao'),
    path('bonificacoes/pdf/<int:pk>/', views.gerar_pdf_bonificacao, name='gerar_pdf_bonificacao'),

    path('api/clientes/', views.api_busca_clientes, name='api_busca_clientes'),
    path('api/busca-produtos/', views.buscar_produto_protheus_unificado, name='api_busca_produtos'),

    path('bonificacoes/exportar/excel/', views.exportar_bonificacoes_excel, name='exportar_bonificacoes_excel'),

    # Solicitação de Chopp (ocultas enquanto CHOPP_ATIVO=False; ver app/permissoes.requer_chopp)
    path('agendamentos/', requer_chopp(agendamento.agendamento_calendario), name='agendamento_calendario'),
    path('agendamentos/novo/', requer_chopp(agendamento.agendamento_novo), name='agendamento_novo'),
    path('agendamentos/<int:pk>/editar/', requer_chopp(agendamento.agendamento_editar), name='agendamento_editar'),
    path('agendamentos/<int:pk>/cancelar/', requer_chopp(agendamento.agendamento_cancelar), name='agendamento_cancelar'),
    path('agendamentos/<int:pk>/agendar/', requer_chopp(agendamento.agendamento_agendar), name='agendamento_agendar'),
    path('agendamentos/confirmar/<str:data>/', requer_chopp(agendamento.agendamento_confirmar_dia), name='agendamento_confirmar_dia'),
    path('agendamentos/pdf/<str:data>/', requer_chopp(agendamento.agendamento_pdf_dia), name='agendamento_pdf_dia'),
    path('agendamentos/api/inadimplencia/', requer_chopp(agendamento.api_inadimplencia), name='agendamento_api_inadimplencia'),
    path('agendamentos/api/titulos/', requer_chopp(agendamento.api_titulos), name='agendamento_api_titulos'),
    path('agendamentos/api/clientes/', requer_chopp(agendamento.api_clientes), name='agendamento_api_clientes'),
    path('agendamentos/api/produtos/', requer_chopp(agendamento.api_produtos), name='agendamento_api_produtos'),
    path('fabrica/', requer_chopp(fabrica.fabrica_dia), name='fabrica_dia'),
    path('fabrica/<int:pk>/entregar/', requer_chopp(fabrica.fabrica_entregar), name='fabrica_entregar'),
    path('fabrica/<int:pk>/nao-retirou/', requer_chopp(fabrica.fabrica_nao_retirou), name='fabrica_nao_retirou'),
    path('fabrica/api/produtos/', requer_chopp(fabrica.fabrica_api_produtos), name='fabrica_api_produtos'),
    path('chopp/', requer_chopp(chopp.chopp_list), name='chopp_list'),
    path('chopp/<int:pk>/processar/', requer_chopp(chopp.chopp_processar), name='chopp_processar'),
    path('chopp/<int:pk>/cancelar/', requer_chopp(chopp.chopp_cancelar), name='chopp_cancelar'),
    path('chopp/exportar/excel/', requer_chopp(chopp.chopp_exportar), name='chopp_exportar'),
    path('api/busca-produtos-chopp/', requer_chopp(chopp.api_busca_produtos_chopp), name='api_busca_produtos_chopp'),
]