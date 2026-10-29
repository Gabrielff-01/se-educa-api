from datetime import timedelta
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APITestCase

from academico.models import Aluno
from auditoria.models import Registro
from contas.models import Usuario

from .demo import pdf_de_exemplo
from .models import Documento

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50


class Base(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=StringIO())
        cls.ana = Aluno.objects.get(nome="Ana Beatriz Souza")
        cls.pedro = Aluno.objects.get(nome="Pedro Henrique Souza")
        cls.hoje = timezone.localdate()

    def entrar(self, username):
        self.client.force_authenticate(Usuario.objects.get(username=username))

    def enviar(self, aluno, tipo="residencia", conteudo=None, nome="doc.pdf", **extra):
        arquivo = SimpleUploadedFile(nome, conteudo if conteudo is not None else pdf_de_exemplo("teste"))
        return self.client.post("/api/documentos/", {"aluno": aluno.pk, "tipo": tipo, "arquivo": arquivo, **extra},
                                format="multipart")


class EnvioTest(Base):
    def test_mae_envia_atestado_e_escola_aceita(self):
        self.entrar("responsavel1")
        r = self.enviar(self.ana, "atestado", data_inicio=self.hoje - timedelta(days=2), data_fim=self.hoje)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["escola"], self.ana.matricula_atual().escola_id)
        self.assertEqual(r.data["enviado_por_nome"], "Maria José Souza (mãe)")
        self.assertNotIn("arquivo", r.data)  # o arquivo não volta na lista
        documento = r.data["id"]

        # A escola do Pedro (escola2) não vê o documento da Ana; a escola1 vê e abre o arquivo.
        self.entrar("escola2")
        self.assertEqual(self.client.get(f"/api/documentos/{documento}/").status_code, 404)
        self.entrar("escola1")
        avisos = [n for n in self.client.get("/api/notificacoes/").data if n["tipo"] == "documento"]
        self.assertTrue(any("Atestado médico" in n["texto"] for n in avisos))
        arquivo = self.client.get(f"/api/documentos/{documento}/arquivo/")
        self.assertEqual(arquivo["Content-Type"], "application/pdf")
        self.assertTrue(arquivo.content.startswith(b"%PDF"))

        r = self.client.post(f"/api/documentos/{documento}/aceitar/", {"resposta": "Melhoras!"}, format="json")
        self.assertEqual((r.status_code, r.data["status"]), (200, "aceito"), r.data)
        self.assertTrue(Registro.objects.filter(tipo="documento", objeto_id=str(documento), acao="editou").exists())
        # Já analisado: não muda mais
        self.assertEqual(self.client.post(f"/api/documentos/{documento}/recusar/", {"resposta": "x"},
                                          format="json").status_code, 400)

        # A mãe é avisada
        self.entrar("responsavel1")
        avisos = [n["titulo"] for n in self.client.get("/api/notificacoes/").data if n["tipo"] == "documento"]
        self.assertIn("Ana · Documento aceito pela escola", avisos)

    def test_recusar_exige_motivo(self):
        self.entrar("aluno1")
        r = self.enviar(self.ana, "foto", PNG, "foto.png")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["tipo_arquivo"], "image/png")
        self.entrar("escola1")
        url = f"/api/documentos/{r.data['id']}/recusar/"
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)
        r = self.client.post(url, {"resposta": "Foto escura."}, format="json")
        self.assertEqual((r.data["status"], r.data["resposta"]), ("recusado", "Foto escura."))

    def test_regras_do_envio(self):
        self.entrar("responsavel1")
        # Atestado sem período
        r = self.enviar(self.ana, "atestado")
        self.assertIn("data_inicio", r.data)
        # Período ao contrário
        r = self.enviar(self.ana, "atestado", data_inicio=self.hoje, data_fim=self.hoje - timedelta(days=3))
        self.assertIn("data_fim", r.data)
        # "Outro" precisa dizer o que é
        self.assertIn("descricao", self.enviar(self.ana, "outro").data)
        # Formato errado (um texto com nome de PDF)
        self.assertIn("arquivo", self.enviar(self.ana, conteudo=b"isso nao e pdf").data)
        # Maior que 5 MB
        grande = b"%PDF" + b"0" * (5 * 1024 * 1024)
        self.assertIn("arquivo", self.enviar(self.ana, conteudo=grande).data)
        # Fora do atestado, o período é ignorado
        r = self.enviar(self.ana, "vacina", data_inicio=self.hoje, data_fim=self.hoje)
        self.assertIsNone(r.data["data_inicio"])

    def test_quem_pode_enviar(self):
        # Aluno de outra família
        outro = Aluno.objects.exclude(pk__in=[self.ana.pk, self.pedro.pk]).filter(
            matriculas__ano_letivo=self.hoje.year).first()
        self.entrar("responsavel1")
        self.assertEqual(self.enviar(outro).status_code, 403)
        # A Ana não envia pelo irmão
        self.entrar("aluno1")
        self.assertEqual(self.enviar(self.pedro).status_code, 403)
        # Escola e professor não enviam
        for usuario in ("escola1", "professor1"):
            self.entrar(usuario)
            self.assertEqual(self.enviar(self.ana).status_code, 403)

    def test_cancelar_so_antes_da_analise(self):
        self.entrar("responsavel1")
        novo = self.enviar(self.pedro, "vacina").data["id"]
        self.entrar("aluno1")  # a Ana não pode cancelar o que a mãe mandou
        self.assertIn(self.client.delete(f"/api/documentos/{novo}/").status_code, (403, 404))
        self.entrar("responsavel1")
        self.assertEqual(self.client.delete(f"/api/documentos/{novo}/").status_code, 204)
        # O aceito da demonstração não dá pra cancelar
        aceito = Documento.objects.get(aluno=self.pedro, status="aceito")
        self.assertEqual(self.client.delete(f"/api/documentos/{aceito.pk}/").status_code, 400)

    def test_lista_de_cada_um(self):
        self.entrar("responsavel1")
        self.assertEqual(len(self.client.get("/api/documentos/").data), 3)  # os 3 da demonstração
        self.entrar("aluno1")
        nomes = {d["aluno_nome"] for d in self.client.get("/api/documentos/").data}
        self.assertEqual(nomes, {"Ana Beatriz Souza"})
        self.entrar("escola1")
        r = self.client.get("/api/documentos/?status=aguardando").data
        self.assertEqual([d["tipo"] for d in r], ["atestado"])
        self.assertIsNotNone(r[0]["faltas_no_periodo"])
        self.entrar("professor1")
        self.assertEqual(self.client.get("/api/documentos/").data, [])


class NaChamadaTest(Base):
    """Atestado aceito pela escola aparece na chamada do professor (a tela pinta de amarelo)."""

    def test_atestado_aceito_aparece_na_chamada(self):
        # A demonstração já tem 2 colegas da Ana com documento aceito; tira pra testar só o da Ana.
        Documento.objects.filter(nome_arquivo__contains="colega").delete()
        turma = self.ana.matricula_atual().turma
        url = f"/api/documentos/na-chamada/?turma={turma.pk}&data={self.hoje.isoformat()}"
        self.entrar("responsavel1")
        r = self.enviar(self.ana, "atestado", data_inicio=self.hoje - timedelta(days=1), data_fim=self.hoje + timedelta(days=2))
        documento = r.data["id"]

        self.entrar("professor1")  # Carlos dá Matemática na turma da Ana
        self.assertEqual(self.client.get(url).data, [])  # ainda aguardando: não aparece
        self.entrar("escola1")
        self.client.post(f"/api/documentos/{documento}/aceitar/", {}, format="json")
        self.entrar("professor1")
        itens = self.client.get(url).data
        self.assertEqual([i["aluno"] for i in itens], [self.ana.pk])
        self.assertEqual(itens[0]["tipo_nome"], "Atestado médico")
        self.assertEqual(itens[0]["data_fim"], self.hoje + timedelta(days=2))
        # Fora do período, não aparece
        depois = (self.hoje + timedelta(days=3)).isoformat()
        self.assertEqual(self.client.get(f"/api/documentos/na-chamada/?turma={turma.pk}&data={depois}").data, [])

    def test_so_quem_da_aula_na_turma(self):
        turma = self.pedro.matricula_atual().turma  # turma do Pedro, em outra escola
        self.entrar("professor1")
        r = self.client.get(f"/api/documentos/na-chamada/?turma={turma.pk}&data={self.hoje.isoformat()}")
        self.assertEqual(r.status_code, 403)
