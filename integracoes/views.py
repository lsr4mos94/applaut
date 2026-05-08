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
    token_recebido = request.META.get('HTTP_X_API_KEY')
    token_esperado = "c6da69cd-3432-40ad-9169-d5444646f7be"

    if token_recebido != token_esperado:
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
                    print(f"✅ Plantão #{plantao.id} atualizado para {novo_status}")
                else:
                    print(f"⚠️ idRef {id_referencia} não encontrado.")
            
            return HttpResponse(status=200)

        except Exception as e:
            print(f"❌ Erro processando Webhook: {str(e)}")
            return HttpResponse(status=400)

    return HttpResponse(status=405)