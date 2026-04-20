from django.urls import path
from . import views

urlpatterns = [
    path('verba/', views.listar_solicitacoes_verba, name='listar_solicitacoes_verba'),
    path('verba/busca-protheus/', views.busca_fornecedor_protheus, name='busca_fornecedor_protheus'),
    
    path('verba/nova/', views.nova_solicitacao_verba, name='nova_solicitacao_verba'),
    path('verba/editar/<int:pk>/', views.editar_solicitacao_verba, name='editar_solicitacao_verba'),
    path('verba/excluir/<int:pk>/', views.excluir_solicitacao_verba, name='excluir_solicitacao_verba'),
    
    path('verba/detalhes/<int:pk>/', views.detalhes_solicitacao_verba, name='detalhes_solicitacao_verba_json'),
    
    path('verba/decidir/<int:pk>/', views.decidir_verba, name='decidir_solicitacao_verba'),
    
    path('verba/concluir/<int:pk>/', views.concluir_verba, name='concluir_solicitacao_verba'),
]