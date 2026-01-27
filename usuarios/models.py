from django.db import models
from django.contrib.auth.models import User

class Perfil(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    
    codigo_vendedor = models.CharField(max_length=10, unique=True, verbose_name="Código do Vendedor")
    
    def __str__(self):
        return f"{self.usuario.username} - {self.codigo_vendedor}"

    class Meta:
        verbose_name = "Perfil"
        verbose_name_plural = "Perfis"