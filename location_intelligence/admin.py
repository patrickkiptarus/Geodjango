from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from .models import Ward, PointOfInterest


@admin.register(Ward)
class WardAdmin(GISModelAdmin):
    list_display = ['name', 'name_key']
    search_fields = ['name', 'name_key']
    gis_widget_kwargs = {
        'attrs': {
            'default_zoom': 11,
            'default_lon': 36.817223,
            'default_lat': -1.286389,
        },
    }


@admin.register(PointOfInterest)
class PointOfInterestAdmin(GISModelAdmin):
    list_display = ['name', 'category', 'major_category', 'ward_name']
    list_filter = ['major_category', 'category', 'ward_name']
    search_fields = ['name', 'category', 'ward_name']
    readonly_fields = ['lat', 'lon']
    gis_widget_kwargs = {
        'attrs': {
            'default_zoom': 11,
            'default_lon': 36.817223,
            'default_lat': -1.286389,
        },
    }