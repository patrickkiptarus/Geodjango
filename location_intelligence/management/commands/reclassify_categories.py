from django.core.management.base import BaseCommand

from location_intelligence.categories import major_category_for
from location_intelligence.models import PointOfInterest


class Command(BaseCommand):
    help = 'Reclassify POI major categories using the shared category map'

    def handle(self, *args, **options):
        updated = 0
        checked = 0

        for poi in PointOfInterest.objects.only('id', 'category', 'major_category').iterator():
            checked += 1
            major_category = major_category_for(poi.category, poi.major_category)
            if major_category == poi.major_category:
                continue
            poi.major_category = major_category
            poi.save(update_fields=['major_category'])
            updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Reclassified {updated} of {checked} POIs.'
        ))
