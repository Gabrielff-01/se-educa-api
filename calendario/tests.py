from io import StringIO

from django.core.management import call_command
from rest_framework.test import APITestCase

from contas.models import Usuario

from .models import CalendarioLetivo


class CalendarioAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())

    def setUp(self):
        self.client.force_authenticate(Usuario.objects.get(username="dies1"))

    def test_calendario_da_rede_conta_dias(self):
        resposta = self.client.get("/api/calendarios/?ano_letivo=2026")
        calendario = resposta.data[0]
        self.assertEqual(calendario["abrangencia"], "Rede estadual")
        self.assertEqual(calendario["dias_letivos"], 200)
        self.assertTrue(calendario["cumpre_minimo"])

    def test_segundo_calendario_da_rede(self):
        dados = {"ano_letivo": 2026, "data_inicio": "2026-02-02", "data_fim": "2026-12-10"}
        resposta = self.client.post("/api/calendarios/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("A rede já tem um calendário", str(resposta.data))

    def test_feriados_pela_api(self):
        dados = {"ano_letivo": 2027, "data_inicio": "2027-02-01", "data_fim": "2027-12-10"}
        criado = self.client.post("/api/calendarios/", dados, format="json")
        self.assertEqual(criado.status_code, 201, criado.data)
        resposta = self.client.post(f"/api/calendarios/{criado.data['id']}/adicionar_feriados/")
        self.assertGreater(resposta.data["criados"], 10)
        self.assertLess(resposta.data["calendario"]["dias_letivos"], 225)
        # rodar de novo não duplica
        de_novo = self.client.post(f"/api/calendarios/{criado.data['id']}/adicionar_feriados/")
        self.assertEqual(de_novo.data["criados"], 0)

    def test_evento_fora_do_calendario(self):
        calendario = CalendarioLetivo.objects.get(ano_letivo=2026, escola=None)
        dados = {"calendario": calendario.pk, "tipo": "feriado", "descricao": "Teste",
                 "data_inicio": "2026-01-05"}
        resposta = self.client.post("/api/eventos/", dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("fora do calendário", resposta.data["data_inicio"][0])

    def test_evento_de_um_dia_guarda_fim_vazio(self):
        calendario = CalendarioLetivo.objects.get(ano_letivo=2026, escola=None)
        dados = {"calendario": calendario.pk, "tipo": "recesso", "descricao": "Ponte",
                 "data_inicio": "2026-03-20", "data_fim": "2026-03-20"}
        resposta = self.client.post("/api/eventos/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertIsNone(resposta.data["data_fim"])
