"""Cadastra as 10 regionais da SEDUC e os 75 municípios de Sergipe, cada um na sua regional.

Fonte: página "Composição da SEED" do site da SEDUC (seduc.se.gov.br/institucional-composicao-seed),
que lista os municípios da DRE 2 à DRE 9. A DEA cuida de Aracaju e a DRE 1 (Estância) fica com
os municípios do Sul Sergipano que sobram (75 no total).
Se uma regional ou município já existir (ex.: "DEA" e "DRE 03" da demonstração), só completa.
As escolas já cadastradas passam para a regional certa do município delas.
"""

from django.db import migrations

REGIONAIS = {
    "DEA": ("Aracaju", ["Aracaju"]),
    "DRE 01": ("Estância", [
        "Arauá", "Boquim", "Cristinápolis", "Estância", "Indiaroba", "Itabaianinha", "Pedrinhas",
        "Salgado", "Santa Luzia do Itanhy", "Tomar do Geru", "Umbaúba",
    ]),
    "DRE 02": ("Lagarto", ["Lagarto", "Poço Verde", "Riachão do Dantas", "Simão Dias", "Tobias Barreto"]),
    "DRE 03": ("Itabaiana", [
        "Areia Branca", "Campo do Brito", "Carira", "Frei Paulo", "Itabaiana", "Macambira", "Malhador",
        "Moita Bonita", "Nossa Senhora Aparecida", "Pedra Mole", "Pinhão", "Ribeirópolis", "São Domingos",
        "São Miguel do Aleixo",
    ]),
    "DRE 04": ("Japaratuba", [
        "Capela", "Carmópolis", "Divina Pastora", "General Maynard", "Japaratuba", "Pirambu",
        "Rosário do Catete", "Santa Rosa de Lima", "Siriri",
    ]),
    "DRE 05": ("Nossa Senhora das Dores", [
        "Aquidabã", "Cumbe", "Feira Nova", "Graccho Cardoso", "Itabi", "Nossa Senhora das Dores",
    ]),
    "DRE 06": ("Propriá", [
        "Amparo de São Francisco", "Brejo Grande", "Canhoba", "Cedro de São João", "Ilha das Flores",
        "Japoatã", "Malhada dos Bois", "Muribeca", "Neópolis", "Pacatuba", "Propriá",
        "Santana do São Francisco", "São Francisco", "Telha",
    ]),
    "DRE 07": ("Gararu", ["Gararu", "Nossa Senhora de Lourdes", "Porto da Folha"]),
    "DRE 08": ("Nossa Senhora do Socorro", [
        "Barra dos Coqueiros", "Itaporanga d'Ajuda", "Laranjeiras", "Maruim", "Nossa Senhora do Socorro",
        "Riachuelo", "Santo Amaro das Brotas", "São Cristóvão",
    ]),
    "DRE 09": ("Nossa Senhora da Glória", [
        "Canindé de São Francisco", "Monte Alegre de Sergipe", "Nossa Senhora da Glória", "Poço Redondo",
    ]),
}


def cadastrar(apps, schema_editor):
    Regional = apps.get_model("rede", "Regional")
    Municipio = apps.get_model("rede", "Municipio")
    for nome, (sede, municipios) in REGIONAIS.items():
        regional, _ = Regional.objects.get_or_create(nome=nome)
        if not regional.sede:
            regional.sede = sede
            regional.save(update_fields=["sede"])
        for municipio in municipios:
            Municipio.objects.get_or_create(nome=municipio, defaults={"regional": regional})

    Escola = apps.get_model("rede", "Escola")
    for escola in Escola.objects.all():
        municipio = Municipio.objects.filter(nome__iexact=escola.municipio.strip()).first()
        if municipio and escola.regional_id != municipio.regional_id:
            escola.regional_id = municipio.regional_id
            escola.municipio = municipio.nome
            escola.save(update_fields=["regional", "municipio"])


class Migration(migrations.Migration):
    dependencies = [
        ("rede", "0005_municipios"),
    ]

    operations = [
        migrations.RunPython(cadastrar, migrations.RunPython.noop),
    ]
