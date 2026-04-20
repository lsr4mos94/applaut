from django.db import models

class LogWebhook(models.Model):
    data_recebimento = models.DateTimeField(auto_now_add=True)
    payload_bruto = models.JSONField()  # Salva o JSON inteiro da Zenvia
    status_processamento = models.CharField(max_length=20, default='Recebido')

    def __str__(self):
        return f"Log {self.id} - {self.data_recebimento}"