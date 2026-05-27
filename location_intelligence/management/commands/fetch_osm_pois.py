import json
from functools import lru_cache
from pathlib import Path

import requests
from django.contrib.gis.geos import Point
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand, CommandError

from location_intelligence.categories import MAJOR_CATEGORY_MAP
from location_intelligence.models import PointOfInterest, Ward


OVERPASS_URL = 'https://overpass-api.de/api/interpreter'

# Approximate Nairobi metropolitan bounding box: south, west, north, east.
DEFAULT_BBOX = '-1.444,36.650,-1.160,37.080'

OSM_TAGS = [
    ('amenity', None),
    ('amenity', 'restaurant'),
    ('amenity', 'cafe'),
    ('amenity', 'bar'),
    ('amenity', 'pub'),
    ('amenity', 'fast_food'),
    ('amenity', 'clinic'),
    ('amenity', 'hospital'),
    ('amenity', 'pharmacy'),
    ('amenity', 'doctors'),
    ('amenity', 'school'),
    ('amenity', 'college'),
    ('amenity', 'university'),
    ('amenity', 'kindergarten'),
    ('amenity', 'bank'),
    ('amenity', 'atm'),
    ('amenity', 'fuel'),
    ('amenity', 'place_of_worship'),
    ('amenity', 'police'),
    ('amenity', 'fire_station'),
    ('amenity', 'drinking_water'),
    ('shop', None),
    ('tourism', 'hotel'),
    ('tourism', 'guest_house'),
    ('tourism', 'hostel'),
    ('tourism', 'museum'),
    ('tourism', 'attraction'),
    ('leisure', 'park'),
    ('leisure', 'sports_centre'),
    ('healthcare', None),
    ('office', None),
    ('craft', None),
    ('emergency', None),
    ('public_transport', None),
    ('railway', 'station'),
    ('railway', 'halt'),
    ('highway', 'bus_stop'),
    ('building', 'school'),
    ('building', 'university'),
    ('building', 'hospital'),
    ('building', 'retail'),
    ('building', 'commercial'),
    ('man_made', None),
    ('historic', None),
    ('club', None),
    ('sport', None),
    ('place', None),
]

@lru_cache(maxsize=1)
def nairobi_boundary_geom():
    boundary_path = Path(__file__).resolve().parents[3] / 'static' / 'data' / 'nairobi_county_boundary.geojson'
    if not boundary_path.exists():
        return None
    data = json.loads(boundary_path.read_text(encoding='utf-8'))
    return GEOSGeometry(json.dumps(data['features'][0]['geometry']), srid=4326)


class Command(BaseCommand):
    help = 'Fetch current Nairobi POIs directly from OpenStreetMap via Overpass API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--bbox',
            default=DEFAULT_BBOX,
            help='Bounding box as south,west,north,east. Default covers Nairobi.',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=120,
            help='Overpass query timeout in seconds.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Only import the first N matched POIs. Useful for testing.',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete existing POIs before importing fresh OSM data.',
        )
        parser.add_argument(
            '--endpoint',
            default=OVERPASS_URL,
            help='Overpass API endpoint.',
        )
        parser.add_argument(
            '--nearest-ward-degrees',
            type=float,
            default=0.03,
            help='Assign POIs just outside ward polygons to nearest ward within this degree distance.',
        )

    def handle(self, *args, **options):
        if not Ward.objects.exists():
            raise CommandError('No wards found. Load ward boundaries before fetching OSM POIs.')

        bbox = self._parse_bbox(options['bbox'])
        query = self._build_overpass_query(bbox, options['timeout'])

        self.stdout.write('Fetching POIs from OpenStreetMap Overpass API...')
        response = requests.post(
            options['endpoint'],
            data={'data': query},
            timeout=options['timeout'] + 30,
            headers={'User-Agent': 'NairobiLocationIntelligence/1.0'},
        )
        response.raise_for_status()
        elements = response.json().get('elements', [])
        self.stdout.write(f'Received {len(elements)} OSM elements')

        if options['clear']:
            deleted, _ = PointOfInterest.objects.all().delete()
            self.stdout.write(f'Deleted {deleted} existing POI records')

        wards = list(Ward.objects.all())
        created = 0
        updated = 0
        skipped = 0
        seen = set()

        for element in elements:
            if options['limit'] and created + updated >= options['limit']:
                break

            poi_data = self._element_to_poi(element)
            if not poi_data:
                skipped += 1
                continue

            dedupe_key = (
                poi_data['name'].lower(),
                poi_data['category'],
                round(poi_data['lat'], 6),
                round(poi_data['lon'], 6),
            )
            if dedupe_key in seen:
                skipped += 1
                continue
            seen.add(dedupe_key)

            point = Point(poi_data['lon'], poi_data['lat'], srid=4326)
            ward = self._find_ward(point, wards, options['nearest_ward_degrees'])
            if not ward:
                skipped += 1
                continue

            defaults = {
                'major_category': poi_data['major_category'],
                'ward_name': ward.name,
                'ward_key': ward.name_key,
                'location': point,
                'lat': poi_data['lat'],
                'lon': poi_data['lon'],
                'data_source': 'osm',
                'external_source_id': poi_data['external_source_id'],
                'inside_nairobi': self._inside_nairobi(point),
            }
            existing = None
            if poi_data['external_source_id']:
                existing = PointOfInterest.objects.filter(
                    external_source_id=poi_data['external_source_id'],
                ).order_by('id').first()
            if not existing:
                existing = PointOfInterest.objects.filter(
                    name=poi_data['name'],
                    category=poi_data['category'],
                    ward=ward,
                ).order_by('id').first()
            if existing:
                for field, value in defaults.items():
                    setattr(existing, field, value)
                existing.save(update_fields=list(defaults.keys()))
                updated += 1
            else:
                PointOfInterest.objects.create(
                    name=poi_data['name'],
                    category=poi_data['category'],
                    ward=ward,
                    **defaults,
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'OSM import complete: {created} created, {updated} updated, {skipped} skipped'
        ))

    def _parse_bbox(self, bbox):
        parts = [part.strip() for part in bbox.split(',')]
        if len(parts) != 4:
            raise CommandError('bbox must be south,west,north,east')
        try:
            return tuple(float(part) for part in parts)
        except ValueError as exc:
            raise CommandError('bbox values must be valid numbers') from exc

    def _build_overpass_query(self, bbox, timeout):
        south, west, north, east = bbox
        bbox_text = f'{south},{west},{north},{east}'
        clauses = []
        seen_clauses = set()
        for key, value in OSM_TAGS:
            if value is None:
                selector = f'["{key}"]'
            else:
                selector = f'["{key}"="{value}"]'
            for clause in (
                f'node{selector}({bbox_text});',
                f'way{selector}({bbox_text});',
                f'relation{selector}({bbox_text});',
            ):
                if clause not in seen_clauses:
                    seen_clauses.add(clause)
                    clauses.append(clause)
        for clause in (
            f'node["name"]({bbox_text});',
            f'way["name"]({bbox_text});',
            f'relation["name"]({bbox_text});',
        ):
            if clause not in seen_clauses:
                seen_clauses.add(clause)
                clauses.append(clause)
        return f"""
        [out:json][timeout:{timeout}];
        (
          {' '.join(clauses)}
        );
        out center tags;
        """

    def _element_to_poi(self, element):
        tags = element.get('tags') or {}
        lat = element.get('lat') or (element.get('center') or {}).get('lat')
        lon = element.get('lon') or (element.get('center') or {}).get('lon')
        if lat is None or lon is None:
            return None

        category = self._category_from_tags(tags)
        if not category:
            return None

        name = (
            tags.get('name')
            or tags.get('brand')
            or tags.get('operator')
            or category.replace('_', ' ').title()
        )
        return {
            'name': str(name)[:200],
            'category': category[:100],
            'major_category': self._major_category(category, tags),
            'lat': float(lat),
            'lon': float(lon),
            'external_source_id': f"{element.get('type', 'element')}/{element.get('id', '')}"[:80],
        }

    def _category_from_tags(self, tags):
        name = (tags.get('name') or '').lower()
        for key in (
            'amenity',
            'shop',
            'tourism',
            'healthcare',
            'leisure',
            'office',
            'craft',
            'emergency',
            'public_transport',
            'railway',
            'highway',
            'building',
            'man_made',
            'historic',
            'club',
            'sport',
            'place',
        ):
            value = tags.get(key)
            if value:
                inferred_category = self._category_from_name(name)
                if str(value) in ('yes', 'retail', 'commercial') and inferred_category:
                    return inferred_category
                if str(value) in ('yes', 'retail', 'commercial') and 'mall' in name:
                    return 'mall'
                return str(value)
        inferred_category = self._category_from_name(name)
        if inferred_category:
            return inferred_category
        if name:
            return 'named_feature'
        return None

    def _category_from_name(self, name):
        if 'mall' in name or 'shopping centre' in name or 'shopping center' in name:
            return 'mall'
        if 'university' in name:
            return 'university'
        if 'college' in name:
            return 'college'
        if 'school' in name:
            return 'school'
        if 'hospital' in name:
            return 'hospital'
        if 'clinic' in name or 'medical centre' in name or 'medical center' in name:
            return 'clinic'
        if 'pharmacy' in name or 'chemist' in name:
            return 'pharmacy'
        if 'hotel' in name:
            return 'hotel'
        if 'restaurant' in name:
            return 'restaurant'
        if 'cafe' in name or 'coffee' in name:
            return 'cafe'
        if 'bank' in name:
            return 'bank'
        return None

    def _major_category(self, category, tags):
        if tags.get('shop'):
            return 'Shopping'
        if tags.get('healthcare'):
            return 'Health'
        return MAJOR_CATEGORY_MAP.get(category, 'Other')

    def _find_ward(self, point, wards, nearest_threshold):
        for ward in wards:
            if ward.geometry.covers(point):
                return ward
        nearest_ward = None
        nearest_distance = None
        for ward in wards:
            distance = ward.geometry.distance(point)
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest_ward = ward
        if nearest_distance is not None and nearest_distance <= nearest_threshold:
            return nearest_ward
        return None

    def _inside_nairobi(self, point):
        boundary = nairobi_boundary_geom()
        if boundary is None:
            return True
        return boundary.covers(point)
