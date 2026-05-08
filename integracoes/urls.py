from django.urls import path
from . import views

urlpatterns = [
    path('zenvia/', views.webhook_plantao, name='webhook_plantao'),
]