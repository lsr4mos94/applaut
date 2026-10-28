import datetime

from django.db import migrations, models


def converter_pedidos(apps, schema_editor):
    """Pedidos de teste lançados no formato antigo: viram ENVIADO com a data/condição que tinham."""
    Pedido = apps.get_model('solicitacoes', 'SolicitacaoChopp')
    for p in Pedido.objects.all():
        p.data_retirada = p.data_entrega or p.data_solicitacao.date()
        p.hora_retirada = datetime.time(6, 0)
        p.condicao_pagamento = (p.prazo_pagamento or '')[:10]
        p.condicao_pagamento_descricao = p.prazo_pagamento or ''
        if p.status == 'PENDENTE':
            p.status = 'ENVIADO'
        p.save(update_fields=['data_retirada', 'hora_retirada', 'condicao_pagamento',
                              'condicao_pagamento_descricao', 'status'])


class Migration(migrations.Migration):

    dependencies = [
        ("solicitacoes", "0012_chopp_historico_faturamento"),
    ]

    operations = [
        migrations.AddField(
            model_name="solicitacaochopp",
            name="data_retirada",
            field=models.DateField(db_index=True, default=datetime.date(2026, 1, 1)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="solicitacaochopp",
            name="hora_retirada",
            field=models.TimeField(default=datetime.time(6, 0)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="solicitacaochopp",
            name="condicao_pagamento",
            field=models.CharField(default="", max_length=10),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="solicitacaochopp",
            name="condicao_pagamento_descricao",
            field=models.CharField(default="", max_length=60),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="solicitacaochopp",
            name="tabela_preco",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="solicitacaochoppitem",
            name="preco_da_tabela",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="solicitacaochopp",
            name="status",
            field=models.CharField(
                choices=[("AGENDADO", "Agendado"), ("ENVIADO", "Enviado"), ("FINALIZADO", "Finalizado"), ("CANCELADO", "Cancelado")],
                db_index=True, default="AGENDADO", max_length=15),
        ),
        migrations.RunPython(converter_pedidos, migrations.RunPython.noop),
        # Defaults antes de remover: permite desfazer a migração mesmo com registros gravados
        migrations.AlterField(model_name="solicitacaochopp", name="recebimento",
                              field=models.CharField(blank=True, default="RETIRADA_FABRICA", max_length=20)),
        migrations.AlterField(model_name="solicitacaochopp", name="prazo_pagamento",
                              field=models.CharField(blank=True, default="", max_length=100)),
        migrations.RemoveField(model_name="solicitacaochopp", name="recebimento"),
        migrations.RemoveField(model_name="solicitacaochopp", name="data_entrega"),
        migrations.RemoveField(model_name="solicitacaochopp", name="prazo_pagamento"),
        migrations.RemoveField(model_name="solicitacaochopp", name="prazo_pagamento_solicitado"),
        migrations.AlterModelOptions(
            name="solicitacaochopp",
            options={"ordering": ["data_retirada", "hora_retirada", "id"],
                     "verbose_name": "Agendamento de Chopp", "verbose_name_plural": "Agendamentos de Chopp"},
        ),
    ]
