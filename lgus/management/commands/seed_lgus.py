"""
Populate the LGU directory with the local government units of Region XIII.

    python manage.py seed_lgus

Region XIII (Caraga) comprises 5 provinces, 6 cities and 67 municipalities -
78 LGUs in total. Butuan City is a highly urbanised city and Surigao City,
Bislig City and Tandag City are recorded with the province they sit in for
geographic grouping.

IMPORTANT: this roster is provided so the directory is usable on day one. It
must be checked against the office's official records before the system is
relied upon - names, income classifications and city classifications change,
and only DILG's own records are authoritative. The command is safe to re-run:
it creates what is missing and leaves existing records alone.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from lgus.models import LGU, LGUType, Province

# province -> (capital, [cities], [municipalities])
CARAGA = {
    "Agusan del Norte": (
        "Cabadbaran City",
        ["Cabadbaran City"],
        [
            "Buenavista", "Carmen", "Jabonga", "Kitcharao", "Las Nieves",
            "Magallanes", "Nasipit", "Remedios T. Romualdez", "Santiago", "Tubay",
        ],
    ),
    "Agusan del Sur": (
        "Prosperidad",
        ["Bayugan City"],
        [
            "Bunawan", "Esperanza", "La Paz", "Loreto", "Prosperidad", "Rosario",
            "San Francisco", "San Luis", "Santa Josefa", "Sibagat", "Talacogon",
            "Trento", "Veruela",
        ],
    ),
    "Surigao del Norte": (
        "Surigao City",
        ["Surigao City"],
        [
            "Alegria", "Bacuag", "Burgos", "Claver", "Dapa", "Del Carmen",
            "General Luna", "Gigaquit", "Mainit", "Malimono", "Pilar", "Placer",
            "San Benito", "San Francisco", "San Isidro", "Santa Monica", "Sison",
            "Socorro", "Tagana-an", "Tubod",
        ],
    ),
    "Surigao del Sur": (
        "Tandag City",
        ["Bislig City", "Tandag City"],
        [
            "Barobo", "Bayabas", "Cagwait", "Cantilan", "Carmen", "Carrascal",
            "Cortes", "Hinatuan", "Lanuza", "Lianga", "Lingig", "Madrid",
            "Marihatag", "San Agustin", "San Miguel", "Tagbina", "Tago",
        ],
    ),
    "Dinagat Islands": (
        "San Jose",
        [],
        [
            "Basilisa", "Cagdianao", "Dinagat", "Libjo", "Loreto", "San Jose",
            "Tubajon",
        ],
    ),
}

# Highly urbanised city, independent of Agusan del Norte.
INDEPENDENT_CITIES = {"Butuan City": "Agusan del Norte"}


class Command(BaseCommand):
    help = "Create the provinces, cities and municipalities of Region XIII (Caraga)."

    @transaction.atomic
    def handle(self, *args, **options):
        created = {"province": 0, "city": 0, "municipality": 0}

        for province_name, (capital, cities, municipalities) in CARAGA.items():
            province, _ = Province.objects.get_or_create(
                name=province_name, defaults={"capital": capital}
            )

            # The province itself is an LGU under the Division's oversight.
            _, is_new = LGU.objects.get_or_create(
                name=f"Province of {province_name}",
                province=province,
                defaults={"lgu_type": LGUType.PROVINCE},
            )
            created["province"] += is_new

            for city in cities:
                _, is_new = LGU.objects.get_or_create(
                    name=city,
                    province=province,
                    defaults={"lgu_type": LGUType.CITY},
                )
                created["city"] += is_new

            for municipality in municipalities:
                _, is_new = LGU.objects.get_or_create(
                    name=municipality,
                    province=province,
                    defaults={"lgu_type": LGUType.MUNICIPALITY},
                )
                created["municipality"] += is_new

        for city, province_name in INDEPENDENT_CITIES.items():
            province = Province.objects.get(name=province_name)
            _, is_new = LGU.objects.get_or_create(
                name=city,
                province=province,
                defaults={"lgu_type": LGUType.CITY, "is_independent": True},
            )
            created["city"] += is_new

        total = LGU.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created['province']} province(s), {created['city']} "
                f"city/cities and {created['municipality']} municipalities."
            )
        )
        self.stdout.write(
            f"The directory now holds {total} LGUs: "
            f"{LGU.objects.filter(lgu_type=LGUType.PROVINCE).count()} provinces, "
            f"{LGU.objects.filter(lgu_type=LGUType.CITY).count()} cities, "
            f"{LGU.objects.filter(lgu_type=LGUType.MUNICIPALITY).count()} municipalities."
        )
        self.stdout.write(
            self.style.WARNING(
                "Verify this roster against the office's official records before "
                "relying on it."
            )
        )
