"""O diagnóstico de egress (GET a serviços de geo-IP no boot) valida TLS com o bundle do
certifi — o mesmo do httpx, com piso no requirements —, não com o ca-certificates da
imagem, que não acompanha o piso (GHSA-6q48-6c7w-9gw2)."""
import ssl
import urllib.request

import certifi

from app.core import automacao


def test_diagnostico_de_egress_usa_o_bundle_do_certifi(monkeypatch):
    vistos = []

    def urlopen_falso(req, timeout=None, context=None):
        vistos.append(context)
        raise OSError("sem rede no teste")

    carregados = []
    original = ssl.SSLContext.load_verify_locations

    def espiao(self, cafile=None, capath=None, cadata=None):
        carregados.append(cafile)
        return original(self, cafile, capath, cadata)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen_falso)
    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", espiao)
    automacao._diagnosticar_egress()

    assert len(vistos) == 2                                   # os dois serviços, com contexto
    assert all(isinstance(c, ssl.SSLContext) and c.verify_mode == ssl.CERT_REQUIRED
               and c.check_hostname for c in vistos)
    assert certifi.where() in carregados
    assert automacao._estado["egress"] == {"erro": "nao_foi_possivel_descobrir_o_ip"}
