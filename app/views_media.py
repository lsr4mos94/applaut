"""
Entrega dos arquivos enviados (pasta media) só para quem pode ver o registro dono do arquivo.
"""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.views.static import serve

from app.permissoes import pode_ver_bonificacao, pode_ver_cadastro, pode_ver_solicitacao_verba


def _registro_permite(user, path):
    from cadastros.models import AnexoCadastro
    from solicitacoes.models import Bonificacao, FotoBonificacao
    from adm.models import SolicitacaoVerba
    from django.db.models import Q

    if path.startswith('cadastros/anexos/'):
        anexo = AnexoCadastro.objects.select_related('cadastro').filter(arquivo=path).first()
        return bool(anexo) and pode_ver_cadastro(user, anexo.cadastro)

    if path.startswith('solicitacoes/verba/'):
        sol = SolicitacaoVerba.objects.filter(Q(arquivo_nota=path) | Q(arquivo_boleto=path)).first()
        return bool(sol) and pode_ver_solicitacao_verba(user, sol)

    if path.startswith('bonificacoes/sac/'):
        bonif = Bonificacao.objects.filter(foto_sac=path).first()
        return bool(bonif) and pode_ver_bonificacao(user, bonif)

    if path.startswith('sac/'):
        foto = FotoBonificacao.objects.select_related('bonificacao').filter(arquivo=path).first()
        return bool(foto) and pode_ver_bonificacao(user, foto.bonificacao)

    # Pastas sem dono conhecido: qualquer usuário logado
    return True


@login_required
def media_protegida(request, path):
    if not _registro_permite(request.user, path):
        raise Http404("Arquivo não encontrado.")
    return serve(request, path, document_root=settings.MEDIA_ROOT)
