"""Documentos de exemplo enviados pela Maria José (responsavel1). Chamado pelo popular_demo.

- Ana Beatriz (Atheneu, escola1): atestado médico esperando análise e um comprovante recusado.
- Pedro Henrique (Gonçalo, escola2): cartão de vacinação já aceito.
- Dois colegas da turma da Ana: um atestado e uma justificativa ACEITOS que cobrem hoje
  (na chamada do professor1 eles aparecem em amarelo).
"""

from datetime import timedelta

from django.utils import timezone

from academico.models import Aluno, Matricula, Presenca
from contas.models import Usuario

from .models import Documento


def pdf_de_exemplo(*linhas):
    """Monta um PDF pequeno (uma página com algumas linhas de texto), só para a demonstração."""
    texto = "BT /F1 16 Tf 60 760 Td 22 TL " + " ".join(
        "(" + linha.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '" for linha in linhas
    ) + " ET"
    conteudo = texto.encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(conteudo) + conteudo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    pdf = b"%PDF-1.4\n"
    posicoes = []
    for numero, objeto in enumerate(objetos, start=1):
        posicoes.append(len(pdf))
        pdf += b"%d 0 obj\n" % numero + objeto + b"\nendobj\n"
    inicio_xref = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % posicao for posicao in posicoes)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, inicio_xref)
    return pdf


def novo(aluno, por, tipo, nome_arquivo, linhas, **extra):
    matricula = aluno.matricula_atual()
    if matricula is None:
        return None
    arquivo = pdf_de_exemplo(*linhas)
    return Documento.objects.create(
        aluno=aluno, escola=matricula.escola, tipo=tipo, arquivo=arquivo, nome_arquivo=nome_arquivo,
        tipo_arquivo="application/pdf", tamanho=len(arquivo), enviado_por=por, **extra)


def criar_documentos_demo():
    if Documento.objects.exists():
        return  # já criados antes: não duplica
    mae = Usuario.objects.filter(username="responsavel1").first()
    escola1 = Usuario.objects.filter(username="escola1").first()
    escola2 = Usuario.objects.filter(username="escola2").first()
    ana = Aluno.objects.filter(nome="Ana Beatriz Souza").first()
    pedro = Aluno.objects.filter(nome="Pedro Henrique Souza").first()
    if not (mae and ana):
        return
    hoje = timezone.localdate()

    # O atestado cobre a última falta da Ana (assim a escola vê "faltas no período").
    falta = (Presenca.objects.filter(matricula__aluno=ana, presente=False, aula__data__lte=hoje)
             .order_by("-aula__data").values_list("aula__data", flat=True).first())
    inicio = falta or hoje - timedelta(days=2)
    fim = min(inicio + timedelta(days=1), hoje)
    novo(ana, mae, Documento.Tipo.ATESTADO, "atestado-ana.pdf",
         ["ATESTADO MÉDICO (exemplo)", "", "Atesto que Ana Beatriz Souza esteve sob meus cuidados",
          f"e precisou de repouso de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}.", "", "Dra. Helena Prado - CRM/SE 0000"],
         data_inicio=inicio, data_fim=fim, descricao="Ela teve virose e ficou em casa.")

    recusado = novo(ana, mae, Documento.Tipo.RESIDENCIA, "conta-de-luz.pdf",
                    ["COMPROVANTE DE RESIDÊNCIA (exemplo)", "", "Conta de energia - referência antiga"])
    if recusado:
        recusado.status = Documento.Status.RECUSADO
        recusado.resposta = "A conta é de mais de 3 meses atrás. Mande uma dos últimos 3 meses, por favor."
        recusado.analisado_por = escola1
        recusado.analisado_em = timezone.now()
        recusado.save()

    if pedro:
        aceito = novo(pedro, mae, Documento.Tipo.VACINA, "vacinas-pedro.pdf",
                      ["CARTÃO DE VACINAÇÃO (exemplo)", "", "Pedro Henrique Souza", "Vacinas em dia."])
        if aceito:
            aceito.status = Documento.Status.ACEITO
            aceito.resposta = "Recebido, obrigado!"
            aceito.analisado_por = escola2
            aceito.analisado_em = timezone.now()
            aceito.save()


def criar_atestados_aceitos_demo():
    """Atestado e justificativa já aceitos pela escola, cobrindo hoje, para dois colegas da Ana.

    Fica separado do criar_documentos_demo pra também entrar em bancos que já tinham os
    documentos da Maria José (confere pelo nome do arquivo, então não duplica).
    """
    ana = Aluno.objects.filter(nome="Ana Beatriz Souza").first()
    escola1 = Usuario.objects.filter(username="escola1").first()
    matricula = ana.matricula_atual() if ana else None
    if matricula is None or Documento.objects.filter(nome_arquivo="atestado-colega-ana.pdf").exists():
        return
    colegas = (Matricula.objects.filter(turma=matricula.turma, situacao=Matricula.Situacao.CONFIRMADA)
               .exclude(aluno__nome__startswith="Ana")  # nome parecido com o da Ana confundiria a demo
               .select_related("aluno").order_by("aluno__nome")[:2])
    hoje = timezone.localdate()
    modelos = [
        (Documento.Tipo.ATESTADO, "atestado-colega-ana.pdf", "ATESTADO MÉDICO (exemplo)", "Recebido. Melhoras!"),
        (Documento.Tipo.JUSTIFICATIVA, "justificativa-colega-ana.pdf", "JUSTIFICATIVA DE FALTA (exemplo)", "Justificativa recebida."),
    ]
    for colega, (tipo, arquivo, titulo, resposta) in zip(colegas, modelos):
        aluno = colega.aluno
        doc = novo(aluno, None, tipo, arquivo,
                   [titulo, "", aluno.nome, f"de {hoje - timedelta(days=1):%d/%m/%Y} a {hoje + timedelta(days=3):%d/%m/%Y}"],
                   data_inicio=hoje - timedelta(days=1), data_fim=hoje + timedelta(days=3))
        if doc:
            doc.status = Documento.Status.ACEITO
            doc.resposta = resposta
            doc.analisado_por = escola1
            doc.analisado_em = timezone.now()
            doc.save()
