from django.urls import path
from . import views

urlpatterns = [
    path('verbas/', views.verbas_mensais, name='verbas_mensais'),
    path('buscar-vendedor/', views.buscar_vendedor_por_codigo, name='buscar_vendedor'),
    path('verbas/salvar/', views.salvar_verba, name='salvar_verba'),
    path('verbas/editar/<int:pk>/', views.editar_verba, name='editar_verba'),
    path('verbas/excluir/<int:pk>/', views.excluir_verba, name='excluir_verba'),

    path('acordos/', views.acordos_comerciais, name='acordos_comerciais'),
    path('acordos/salvar/', views.salvar_acordo, name='salvar_acordo'),
    path('acordos/excluir/<int:pk>/', views.excluir_acordo, name='excluir_acordo'),

    path('clientes', views.lista_cadastros, name='lista_cadastros'),
    path('clientes/novo/', views.criar_cadastro, name='criar_cadastro'),
    path('clientes/<int:pk>/detalhes/', views.detalhes_cadastro, name='detalhes_cadastro'),
    path('clientes/<int:pk>/editar/', views.editar_cadastro, name='editar_cadastro'),
    path('clientes/<int:pk>/status/', views.processar_status, name='processar_status'),

    path('api/historico/<int:acordo_id>/', views.api_historico_acordo, name='api_historico_acordo'),

]