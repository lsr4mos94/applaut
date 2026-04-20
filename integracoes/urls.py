from django.urls import path
from . import views

urlpatterns = [
    path('zenvia/', views.webhook_zenvia, name='zenvia_webhook'),
]