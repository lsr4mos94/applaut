from django.core.management.base import BaseCommand

from cadastros.models import AcordoComercial


class Command(BaseCommand):
    help = (
        "Encerra os acordos comerciais ATIVOS cujo saldo já foi totalmente "
        "consumido por bonificações. Rode uma vez após publicar o encerramento automático."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--aplicar',
            action='store_true',
            help="Grava as alterações. Sem esta opção o comando apenas lista os acordos.",
        )

    def handle(self, *args, **options):
        encontrados = 0
        for acordo in AcordoComercial.objects.filter(situacao='ATIVO'):
            # Só considera acordos que já tiveram consumo (ignora acordos sem limite cadastrado)
            if not acordo._utilizacoes().exists() or acordo.saldo_disponivel > 0:
                continue

            encontrados += 1
            self.stdout.write(f"Acordo #{acordo.id} - {acordo.cliente_nome}: saldo zerado")
            if options['aplicar']:
                acordo.atualizar_situacao()

        if options['aplicar']:
            self.stdout.write(self.style.SUCCESS(f"{encontrados} acordo(s) encerrado(s)."))
        else:
            self.stdout.write(f"{encontrados} acordo(s) seriam encerrados. Use --aplicar para gravar.")
