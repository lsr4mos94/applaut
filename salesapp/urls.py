from django.urls import path
from . import views
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

app_name = 'salesapp'

urlpatterns = [
    path('', views.user_login, name='login'),
    path('inicio/', views.inicio, name='inicio'),
    path('novo/', views.novo_cadastro, name='novo_cadastro'),
    path('submit/', views.novo_cadastro_submit, name='novo_cadastro_submit'),
    path('cadastros/', views.cadastros, name='cadastros'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),

    path('cadastro/confirmar/<int:cadastro_id>/', views.cadastro_confirmar, name='cadastro_confirmar'),
    path('cadastro/rejeitar/<int:cadastro_id>/', views.cadastro_rejeitar, name='cadastro_rejeitar'),

    path('cadastro/liberar/<int:cadastro_id>/', views.liberar_cadastro, name='liberar_cadastro'),
    path('cadastro/bloquear/<int:cadastro_id>/', views.bloquear_cadastro, name='bloquear_cadastro'),

    path('nova_bonificacao/submit/', views.nova_bonificacao_submit, name='nova_bonificacao_submit'),
    path('bonificacoes/', views.bonificacoes, name='bonificacoes'),
    path('nova_bonificacao/', views.nova_bonificacao, name='nova_bonificacao'),
    path('api/buscar-clientes/', views.buscar_clientes, name='buscar_clientes_api'),
    path('api/buscar-produtos/', views.buscar_produtos, name='buscar_produtos_api'), 

    path('bonificacao/autorizar_gestor/<int:bonificacao_id>/', views.bonificacao_autorizar_gestor, name='bonificacao_autorizar_gestor'),
    path('bonificacao/recusar_gestor/<int:bonificacao_id>/', views.bonificacao_recusar_gestor, name='bonificacao_recusar_gestor'),

    path('bonificacao/bonificacao_pedido/<int:bonificacao_id>/', views.bonificacao_pedido, name='bonificacao_pedido'),

]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)