from django.urls import path
from . import views

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
]