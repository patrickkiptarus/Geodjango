from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.db.models import Q


class Ward(models.Model):
    """Model for Nairobi ward boundaries"""
    name = models.CharField(max_length=100, unique=True)
    name_key = models.CharField(max_length=100, unique=True)  # For searching
    geometry = models.MultiPolygonField(srid=4326)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PointOfInterest(models.Model):
    """Model for Points of Interest in Nairobi"""
    DATA_SOURCE_CHOICES = [
        ('osm', 'OpenStreetMap'),
        ('local', 'Local backup'),
    ]

    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)  # Raw OSM category
    major_category = models.CharField(max_length=100)  # Grouped category
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='pois')
    ward_name = models.CharField(max_length=100)  # Denormalized for performance
    ward_key = models.CharField(max_length=100)  # Denormalized for performance
    location = models.PointField(srid=4326)
    lat = models.FloatField()
    lon = models.FloatField()
    data_source = models.CharField(max_length=20, choices=DATA_SOURCE_CHOICES, default='local')
    external_source_id = models.CharField(max_length=80, blank=True, default='')
    inside_nairobi = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['major_category']),
            models.Index(fields=['category']),
            models.Index(fields=['ward_key']),
            models.Index(fields=['name']),
            models.Index(fields=['data_source']),
            models.Index(fields=['external_source_id']),
            models.Index(fields=['inside_nairobi']),
        ]

    def __str__(self):
        return f"{self.name} ({self.category})"

    @property
    def coordinates(self):
        return (self.lat, self.lon)

    @classmethod
    def get_major_categories(cls):
        """Get distinct major categories"""
        return cls.objects.values_list('major_category', flat=True).distinct().order_by('major_category')

    @classmethod
    def get_categories(cls):
        """Get distinct raw categories"""
        return cls.objects.values_list('category', flat=True).distinct().order_by('category')

    @classmethod
    def filter_by_criteria(cls, major_category=None, category=None, ward=None, search_name=None):
        """Filter POIs by various criteria"""
        queryset = cls.objects.all()

        if major_category and major_category != 'All':
            queryset = queryset.filter(major_category=major_category)

        if category and category != 'All':
            queryset = queryset.filter(category=category)

        if ward and ward != 'All':
            queryset = queryset.filter(ward__name=ward)

        if search_name and search_name.strip():
            search_term = search_name.strip()
            variants = {
                search_term,
                search_term.replace(' ', '-'),
                search_term.replace('-', ' '),
                search_term.replace(' ', ''),
                search_term.replace('-', ''),
            }
            search_query = Q()
            for variant in variants:
                if variant:
                    search_query |= Q(name__icontains=variant)
            queryset = queryset.filter(search_query)

        return queryset

    def distance_to(self, lat, lon):
        """Calculate distance to a point in kilometers using Haversine formula"""
        import math

        # Convert to radians
        lat1_rad = math.radians(self.lat)
        lon1_rad = math.radians(self.lon)
        lat2_rad = math.radians(lat)
        lon2_rad = math.radians(lon)

        # Haversine formula
        dlon = lon2_rad - lon1_rad
        dlat = lat2_rad - lat1_rad
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = 6371 * c  # Earth's radius in km

        return distance
