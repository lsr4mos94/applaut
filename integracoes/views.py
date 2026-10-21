import hmac
import json
import logging
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import LogWebhook
from solicitacoes.models import Plantao
from django.utils import timezone

logger = logging.getLogger(__name__)

@csrf_exempt
def webhook_plantao(request):
    token_recebido = request.META.get('HTTP_X_API_KEY') or ''
    token_esperado = settings.WEBHOOK_PLANTAO_TOKEN

    if not token_esperado:
        logger.error("WEBHOOK_PLANTAO_TOKEN não configurado no .env; webhook recusado.")
        return HttpResponse("Não autorizado", status=401)
    if not hmac.compare_digest(token_recebido.encode(), token_esperado.encode()):
        return HttpResponse("Não autorizado", status=401)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            message_data = data.get('message', {})
            
            id_referencia = message_data.get('idRef') 
            contents = message_data.get('contents', [])

            if id_referencia and contents:
                texto_botao = contents[0].get('text', '').upper()
                novo_status = 'CONFIRMADO' if 'ATENDIDA' in texto_botao else 'RECUSADO'

                plantao = Plantao.objects.filter(zenvia_message_id=id_referencia).first()

                if plantao:
                    plantao.status = novo_status
                    plantao.save()
                    logger.info(f"Plantão #{plantao.id} atualizado para {novo_status} pelo webhook")
                else:
                    logger.warning(f"Webhook de plantão: idRef {id_referencia} não encontrado")
            
            return HttpResponse(status=200)

        except Exception as e:
            logger.exception("Erro processando webhook de plantão")
            return HttpResponse(status=400)

    return HttpResponse(status=405)