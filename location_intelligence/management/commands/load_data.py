import os
import json
from functools import lru_cache
from pathlib import Path
import pandas as pd
from django.core.management.base import BaseCommand
from django.contrib.gis.geos import GEOSGeometry, Point, MultiPolygon
from location_intelligence.models import Ward, PointOfInterest


@lru_cache(maxsize=1)
def nairobi_boundary_geom():
    boundary_path = Path(__file__).resolve().parents[3] / 'static' / 'data' / 'nairobi_county_boundary.geojson'
    if not boundary_path.exists():
        return None
    data = json.loads(boundary_path.read_text(encoding='utf-8'))
    return GEOSGeometry(json.dumps(data['features'][0]['geometry']), srid=4326)


class Command(BaseCommand):
    help = 'Load POI and ward data from the original Shiny app data files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data-dir',
            type=str,
            default='../data',
            help='Directory containing the data files (default: ../data)'
        )

    def handle(self, *args, **options):
        data_dir = options['data_dir']

        # Load ward boundaries
        self.stdout.write('Loading ward boundaries...')
        wards_path = os.path.join(data_dir, 'geoBoundaries-KEN-ADM3.geojson')
        if not os.path.exists(wards_path):
            self.stderr.write(f'Ward boundaries file not found: {wards_path}')
            return

        with open(wards_path, encoding='utf-8') as wards_file:
            wards_geojson = json.load(wards_file)

        wards_created = 0
        for feature in wards_geojson.get('features', []):
            properties = feature.get('properties', {})
            ward_name = str(properties.get('shapeName', '')).strip()
            if not ward_name:
                continue
            ward_key = ward_name.lower().strip().replace(' ', '_')

            geom = GEOSGeometry(json.dumps(feature.get('geometry')), srid=4326)
            if geom.geom_type == 'Polygon':
                geom = MultiPolygon(geom, srid=4326)

            ward, created = Ward.objects.get_or_create(
                name=ward_name,
                defaults={
                    'name_key': ward_key,
                    'geometry': geom
                }
            )
            if created:
                wards_created += 1

        self.stdout.write(f'Created {wards_created} wards')

        # Load POI data
        self.stdout.write('Loading POI data...')
        poi_path = os.path.join(data_dir, 'poi_nairobi.rds')
        if not os.path.exists(poi_path):
            self.stderr.write(f'POI data file not found: {poi_path}')
            return

        # For now, we'll assume the data is available as CSV or we need to convert
        # Since we can't read RDS directly, let's check if there's a CSV version
        poi_csv_path = os.path.join(data_dir, 'poi_nairobi.csv')
        if os.path.exists(poi_csv_path):
            poi_df = pd.read_csv(poi_csv_path)
        else:
            self.stderr.write('POI data must be converted to CSV format first')
            self.stderr.write('Run the prepare_data.R script to generate poi_nairobi.rds, then convert to CSV')
            return

        pois_created = 0
        boundary = nairobi_boundary_geom()
        for _, row in poi_df.iterrows():
            ward_name = str(row['ward_name'])
            try:
                ward = Ward.objects.get(name=ward_name)
            except Ward.DoesNotExist:
                self.stderr.write(f'Ward not found: {ward_name}, skipping POI')
                continue

            point = Point(float(row['lon']), float(row['lat']), srid=4326)
            poi, created = PointOfInterest.objects.get_or_create(
                name=str(row['name']),
                category=str(row['category']),
                ward=ward,
                location=point,
                defaults={
                    'major_category': str(row['major_category']),
                    'ward_name': ward_name,
                    'ward_key': ward.name_key,
                    'lat': float(row['lat']),
                    'lon': float(row['lon']),
                    'data_source': 'local',
                    'external_source_id': '',
                    'inside_nairobi': boundary.covers(point) if boundary is not None else True,
                }
            )
            if created:
                pois_created += 1

        self.stdout.write(f'Created {pois_created} POIs')
        self.stdout.write('Data loading complete!')
