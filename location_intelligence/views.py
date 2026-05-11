import json
import math
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from django.core.cache import cache
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from django.db.models import Count, Q
from .models import PointOfInterest, Ward


MAP_POI_LIMIT = 5000


@lru_cache(maxsize=1)
def _nairobi_boundary_geom():
    boundary_path = Path(__file__).resolve().parent.parent / 'static' / 'data' / 'nairobi_county_boundary.geojson'
    if not boundary_path.exists():
        return None
    from django.contrib.gis.geos import GEOSGeometry
    data = json.loads(boundary_path.read_text(encoding='utf-8'))
    feature = data['features'][0]
    return GEOSGeometry(json.dumps(feature['geometry']), srid=4326)


def _clip_to_nairobi(queryset):
    return queryset.filter(inside_nairobi=True)


def _selected_ward_geometry(ward_name):
    if not ward_name or ward_name == 'All':
        return None

    try:
        geometry = Ward.objects.get(name=ward_name).geometry
    except Ward.DoesNotExist:
        return None

    boundary = _nairobi_boundary_geom()
    if boundary is not None:
        clipped_geometry = geometry.intersection(boundary)
        if not clipped_geometry.empty:
            return clipped_geometry
    return geometry


def _apply_selected_ward_geometry(queryset, ward_name):
    geometry = _selected_ward_geometry(ward_name)
    if geometry is None:
        if ward_name and ward_name != 'All':
            return queryset.none(), None
        return queryset, None
    return queryset.filter(location__coveredby=geometry), geometry


def _filtered_pois(major_category=None, category=None, ward=None, search_name=None):
    queryset = PointOfInterest.filter_by_criteria(
        major_category=major_category,
        category=category,
        search_name=search_name
    )
    queryset = _clip_to_nairobi(queryset)
    return _apply_selected_ward_geometry(queryset, ward)


def _map_buffer_insights(total_pois, visible_pois, service_label, ward_filter, buffer_radius_m, show_buffers):
    radius_km = buffer_radius_m / 1000
    estimated_area = visible_pois * math.pi * (radius_km ** 2)
    if total_pois == 0:
        message = 'No matching services were found. This may indicate an underserved area or missing map data.'
        status = 'Needs field check'
    elif total_pois <= 3:
        message = 'Very few matching services were found. Check surrounding wards or validate whether local services are unmapped.'
        status = 'Likely underserved'
    elif total_pois <= 10:
        message = 'Some services exist, but coverage may still be uneven. Use the buffers to inspect uncovered pockets.'
        status = 'Moderate coverage'
    else:
        message = 'Many services are mapped. Use buffers and nearest analysis to inspect local access gaps.'
        status = 'Mapped coverage'

    area_label = f'{estimated_area:.1f} sq km' if show_buffers else 'Buffers off'
    return {
        'service_label': service_label,
        'place_scope': ward_filter if ward_filter != 'All' else 'Nairobi',
        'radius_km': round(radius_km, 2),
        'estimated_area': area_label,
        'status': status,
        'message': message,
    }


OPPORTUNITY_PROFILES = {
    'pharmacy': {
        'label': 'Pharmacy / Clinic',
        'target_categories': ['pharmacy', 'clinic', 'hospital', 'doctors', 'dentist'],
        'target_major': ['Health'],
        'demand_major': ['Education', 'Accommodation', 'Food & Drink', 'Transport'],
        'access_major': ['Transport', 'Finance'],
        'description': 'Find wards with strong daily activity but relatively low health-service coverage.',
    },
    'restaurant': {
        'label': 'Restaurant / Cafe',
        'target_categories': ['restaurant', 'cafe', 'fast_food', 'bar', 'pub'],
        'target_major': ['Food & Drink'],
        'demand_major': ['Education', 'Accommodation', 'Transport', 'Shopping'],
        'access_major': ['Transport', 'Finance'],
        'description': 'Identify high-footfall wards where food options may still be under-supplied.',
    },
    'retail': {
        'label': 'Retail / Shop',
        'target_categories': [],
        'target_major': ['Shopping'],
        'demand_major': ['Food & Drink', 'Education', 'Accommodation', 'Transport'],
        'access_major': ['Transport', 'Finance'],
        'description': 'Rank wards for general retail using activity generators and existing competition.',
    },
    'banking': {
        'label': 'Bank / ATM',
        'target_categories': ['bank', 'atm'],
        'target_major': ['Finance'],
        'demand_major': ['Shopping', 'Food & Drink', 'Transport', 'Education'],
        'access_major': ['Transport'],
        'description': 'Find commercial wards with activity but fewer finance access points.',
    },
    'school': {
        'label': 'School / Training Centre',
        'target_categories': ['school', 'college', 'university', 'kindergarten'],
        'target_major': ['Education'],
        'demand_major': ['Accommodation', 'Transport', 'Shopping'],
        'access_major': ['Transport'],
        'description': 'Locate areas with supporting urban activity and lower education saturation.',
    },
    'hotel': {
        'label': 'Hotel / Guest House',
        'target_categories': ['hotel', 'guest_house', 'hostel', 'motel'],
        'target_major': ['Accommodation'],
        'demand_major': ['Entertainment', 'Food & Drink', 'Transport', 'Government'],
        'access_major': ['Transport', 'Finance'],
        'description': 'Surface wards with visitor-supporting services but fewer accommodation options.',
    },
}


def index(request):
    """Main page - redirects to map explorer"""
    return map_explorer(request)


def map_explorer(request):
    """Map explorer page with filters and interactive map"""
    ward_ids = (
        PointOfInterest.objects
        .filter(inside_nairobi=True)
        .order_by()
        .values_list('ward_id', flat=True)
        .distinct()
    )
    ward_queryset = Ward.objects.filter(id__in=ward_ids).order_by('name')
    category_pairs = list(
        PointOfInterest.objects.filter(inside_nairobi=True)
        .values('major_category', 'category')
        .distinct()
        .order_by('major_category', 'category')
    )
    category_groups = {}
    for item in category_pairs:
        category_groups.setdefault(item['major_category'], []).append(item['category'])

    # Get filter options
    major_categories = ['All'] + list(
        PointOfInterest.objects.filter(inside_nairobi=True)
        .values_list('major_category', flat=True)
        .distinct()
        .order_by('major_category')
    )
    categories = ['All'] + list(
        PointOfInterest.objects.filter(inside_nairobi=True)
        .values_list('category', flat=True)
        .distinct()
        .order_by('category')
    )
    wards = ['All'] + list(ward_queryset.values_list('name', flat=True).order_by('name'))

    # Get current filter values from request
    major_category = request.GET.get('major_category', 'All')
    category = request.GET.get('category', 'All')
    ward_filter = request.GET.get('ward', 'All')
    search_name = request.GET.get('search_name', '')
    use_clusters = request.GET.get('use_clusters', 'on') in ('on', 'true', '1')
    show_buffers_value = request.GET.get('show_buffers')
    if show_buffers_value is None:
        show_buffers = major_category != 'All' or category != 'All' or ward_filter != 'All'
    else:
        show_buffers = show_buffers_value in ('on', 'true', '1')
    try:
        buffer_radius_m = int(request.GET.get('buffer_radius_m', 750))
    except (TypeError, ValueError):
        buffer_radius_m = 750
    buffer_radius_m = min(max(buffer_radius_m, 100), 5000)

    # Apply filters. Ward filtering uses the actual ward polygon so POIs are
    # shown by location even if an imported ward label was imperfect.
    pois, selected_ward_geom = _filtered_pois(
        major_category=major_category,
        category=category,
        ward=ward_filter,
        search_name=search_name
    )

    # Get statistics
    total_pois = pois.count()
    if total_pois > 0:
        top_category = pois.values('major_category').annotate(
            count=Count('major_category')
        ).order_by('-count').first()['major_category']
    else:
        top_category = 'No data'

    map_pois = list(pois[:MAP_POI_LIMIT])
    service_label = category if category != 'All' else major_category
    if service_label == 'All':
        service_label = 'all selected services'
    buffer_insights = _map_buffer_insights(
        total_pois=total_pois,
        visible_pois=len(map_pois),
        service_label=service_label,
        ward_filter=ward_filter,
        buffer_radius_m=buffer_radius_m,
        show_buffers=show_buffers,
    )

    context = {
        'major_categories': major_categories,
        'categories': categories,
        'category_groups': category_groups,
        'wards': wards,
        'selected_major_category': major_category,
        'selected_category': category,
        'selected_ward': ward_filter,
        'search_name': search_name,
        'use_clusters': use_clusters,
        'show_buffers': show_buffers,
        'buffer_radius_m': buffer_radius_m,
        'buffer_insights': buffer_insights,
        'total_pois': total_pois,
        'top_category': top_category,
        'selected_ward_geom': selected_ward_geom,
        'pois': map_pois,
        'visible_pois': len(map_pois),
        'map_poi_limit': MAP_POI_LIMIT,
        'all_wards': ward_queryset if ward_filter == 'All' else [],
    }

    return render(request, 'location_intelligence/map_explorer.html', context)


def place_results(request):
    """Data table view of filtered places"""
    # Same filtering logic as map_explorer
    major_category = request.GET.get('major_category', 'All')
    category = request.GET.get('category', 'All')
    ward_filter = request.GET.get('ward', 'All')
    search_name = request.GET.get('search_name', '')

    pois, _ = _filtered_pois(
        major_category=major_category,
        category=category,
        ward=ward_filter,
        search_name=search_name
    )
    total_pois = pois.count()
    paginator = Paginator(pois.only(
        'name',
        'ward_name',
        'major_category',
        'category',
        'data_source',
        'lat',
        'lon',
    ), 100)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    query_params = request.GET.copy()
    query_params.pop('page', None)

    context = {
        'pois': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'page_range': paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=2),
        'query_string': query_params.urlencode(),
        'total_pois': total_pois,
    }

    return render(request, 'location_intelligence/place_results.html', context)


@require_POST
def find_nearest(request):
    """AJAX endpoint to find nearest places"""
    try:
        lat = float(request.POST.get('lat', -1.286389))
        lon = float(request.POST.get('lon', 36.817223))
        k = int(request.POST.get('k', 5))

        # Apply current filters
        major_category = request.POST.get('major_category', 'All')
        category = request.POST.get('category', 'All')
        ward_filter = request.POST.get('ward', 'All')
        search_name = request.POST.get('search_name', '')

        pois, _ = _filtered_pois(
            major_category=major_category,
            category=category,
            ward=ward_filter,
            search_name=search_name
        )

        # Calculate distances and sort
        user_point = Point(lon, lat, srid=4326)
        nearest_pois = []

        for poi in pois:
            distance = poi.distance_to(lat, lon)
            nearest_pois.append({
                'id': poi.id,
                'name': poi.name,
                'category': poi.category,
                'major_category': poi.major_category,
                'ward_name': poi.ward_name,
                'lat': poi.lat,
                'lon': poi.lon,
                'distance': round(distance, 2)
            })

        # Sort by distance and take top k
        nearest_pois.sort(key=lambda x: x['distance'])
        nearest_pois = nearest_pois[:k]

        return JsonResponse({
            'success': True,
            'nearest_places': nearest_pois,
            'user_location': {'lat': lat, 'lon': lon}
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


def business_insights(request):
    """Business insights page with plots and analysis"""
    # Apply current filters
    major_category = request.GET.get('major_category', 'All')
    category = request.GET.get('category', 'All')
    ward_filter = request.GET.get('ward', 'All')
    search_name = request.GET.get('search_name', '')

    pois, _ = _filtered_pois(
        major_category=major_category,
        category=category,
        ward=ward_filter,
        search_name=search_name
    )

    # Get major category distribution
    major_dist = pois.values('major_category').annotate(
        count=Count('major_category')
    ).order_by('-count')

    # Get top specific categories
    category_dist = pois.values('category').annotate(
        count=Count('category')
    ).order_by('-count')[:15]

    # Generate business insight text
    if major_dist:
        top_categories = [item['major_category'] for item in major_dist[:3]]
        insight_text = f"This area is currently dominated by {', '.join(top_categories)} places. A business user can compare these dominant categories with lower-count categories to identify possible underserved opportunities."
    else:
        insight_text = "No POI data is available for the current filters."

    # Ward business summary
    ward_summary = pois.values('major_category', 'category').annotate(
        count=Count('id')
    ).order_by('-count')

    context = {
        'major_distribution': list(major_dist),
        'category_distribution': list(category_dist),
        'business_insight': insight_text,
        'ward_summary': list(ward_summary),
        'total_pois': pois.count(),
    }

    return render(request, 'location_intelligence/business_insights.html', context)


def opportunity_analysis(request):
    """Rank wards by opportunity for selected business or service type."""
    selected_profile_key = request.GET.get('profile', 'pharmacy')
    profile = OPPORTUNITY_PROFILES.get(selected_profile_key, OPPORTUNITY_PROFILES['pharmacy'])
    results = _cached_opportunity_scores(selected_profile_key, profile)
    top_results = results[:30]

    context = {
        'profiles': OPPORTUNITY_PROFILES,
        'selected_profile_key': selected_profile_key,
        'selected_profile': profile,
        'results': top_results,
        'top_five': top_results[:5],
        'chart_labels': [item['ward'] for item in top_results[:12]],
        'chart_scores': [item['score'] for item in top_results[:12]],
        'ward_score_geojson': _opportunity_geojson(top_results),
        'total_wards_scored': len(results),
    }
    return render(request, 'location_intelligence/opportunity_analysis.html', context)


def data_science_insights(request):
    """Community needs dashboard powered by the data science layer."""
    insights = _cached_data_science_insights()
    selected_ward = request.GET.get('ward') or (
        insights['service_gaps'][0]['ward'] if insights['service_gaps'] else ''
    )
    context = {
        **insights,
        'selected_ward': selected_ward,
        'ward_report': _community_ward_report(selected_ward, insights['service_gaps_all']),
    }
    return render(request, 'location_intelligence/data_science_insights.html', context)


def _cached_data_science_insights():
    total_pois = PointOfInterest.objects.count()
    cache_key = f'data_science_insights:v3:{total_pois}'
    insights = cache.get(cache_key)
    if insights is None:
        insights = _build_data_science_insights()
        cache.set(cache_key, insights, 60 * 30)
    return insights


def _build_data_science_insights():
    pois = list(
        PointOfInterest.objects
        .filter(inside_nairobi=True)
        .order_by()
        .values('id', 'name', 'category', 'major_category', 'ward_name', 'lat', 'lon', 'data_source')
    )
    total = len(pois)
    osm_count = sum(1 for poi in pois if _poi_get(poi, 'data_source') == 'osm')
    local_count = total - osm_count
    vague_count = sum(1 for poi in pois if _is_vague_poi(poi))
    other_count = sum(1 for poi in pois if _poi_get(poi, 'major_category') == 'Other')
    service_gaps_all = _service_gap_summary()
    service_gaps = service_gaps_all[:20]
    category_quality = _category_quality_summary(pois)
    service_counts = _essential_service_counts(pois)

    avg_quality = round(
        sum(_poi_quality_score(poi) for poi in pois) / total
    ) if total else 0
    avg_gap = round(sum(item['gap_score'] for item in service_gaps_all) / len(service_gaps_all), 2) if service_gaps_all else 0
    strongest_need = service_gaps[0] if service_gaps else None

    return {
        'total_pois': total,
        'osm_count': osm_count,
        'local_count': local_count,
        'osm_share': round(osm_count / total * 100) if total else 0,
        'avg_quality': avg_quality,
        'vague_count': vague_count,
        'vague_share': round(vague_count / total * 100) if total else 0,
        'other_count': other_count,
        'other_share': round(other_count / total * 100) if total else 0,
        'service_gaps': service_gaps,
        'service_gaps_all': service_gaps_all,
        'service_counts': service_counts,
        'category_quality': category_quality,
        'avg_gap': avg_gap,
        'strongest_need': strongest_need,
        'wards_analyzed': len(service_gaps_all),
        'priority_actions': _priority_actions(service_gaps),
    }


def _is_vague_poi(poi):
    return _poi_get(poi, 'category') in ('yes', 'named_feature') or _poi_get(poi, 'major_category') == 'Other'


def _poi_quality_score(poi):
    score = 100
    name = _poi_get(poi, 'name') or ''
    if _poi_get(poi, 'data_source') != 'osm':
        score -= 10
    if _poi_get(poi, 'category') in ('yes', 'named_feature'):
        score -= 28
    if _poi_get(poi, 'major_category') == 'Other':
        score -= 20
    if not name or len(name.strip()) <= 2:
        score -= 18
    if any(char.isdigit() for char in name) and len(name.strip()) <= 6:
        score -= 8
    return max(0, min(100, score))


def _poi_quality_item(poi):
    issues = []
    name = _poi_get(poi, 'name') or ''
    if _poi_get(poi, 'data_source') != 'osm':
        issues.append('local backup')
    if _poi_get(poi, 'category') in ('yes', 'named_feature'):
        issues.append('vague OSM tag')
    if _poi_get(poi, 'major_category') == 'Other':
        issues.append('unclassified')
    if not name or len(name.strip()) <= 2:
        issues.append('weak name')
    return {
        'name': name,
        'ward': _poi_get(poi, 'ward_name'),
        'category': _poi_get(poi, 'category'),
        'major_category': _poi_get(poi, 'major_category'),
        'source': _poi_get(poi, 'data_source'),
        'score': _poi_quality_score(poi),
        'issues': ', '.join(issues) if issues else 'ok',
    }


def _poi_get(poi, field):
    if isinstance(poi, dict):
        return poi.get(field)
    return getattr(poi, field)


def _normalise_place_name(name):
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower())


def _duplicate_candidates(pois):
    buckets = defaultdict(list)
    for poi in pois:
        key = _normalise_place_name(_poi_get(poi, 'name'))
        if len(key) < 5:
            continue
        # About 10-12 m buckets near Nairobi. Good enough for review candidates.
        buckets[(key, round(_poi_get(poi, 'lat'), 4), round(_poi_get(poi, 'lon'), 4))].append(poi)

    candidates = []
    for group in buckets.values():
        if len(group) < 2:
            continue
        candidates.append({
            'name': _poi_get(group[0], 'name'),
            'count': len(group),
            'ward': _poi_get(group[0], 'ward_name'),
            'category': _poi_get(group[0], 'category'),
            'sources': ', '.join(sorted({_poi_get(poi, 'data_source') for poi in group})),
            'lat': round(_poi_get(group[0], 'lat'), 6),
            'lon': round(_poi_get(group[0], 'lon'), 6),
        })
    return sorted(candidates, key=lambda item: item['count'], reverse=True)


SERVICE_GAP_TARGETS = {
    'Health': {'major': {'Health'}, 'label': 'health facility'},
    'Education': {'major': {'Education'}, 'label': 'school or college'},
    'Shopping': {'major': {'Shopping'}, 'label': 'shop or mall'},
    'Finance': {'major': {'Finance'}, 'label': 'bank or ATM'},
    'Transport': {'major': {'Transport'}, 'label': 'transport point'},
}


def _service_gap_summary():
    ward_ids = (
        PointOfInterest.objects
        .filter(inside_nairobi=True)
        .order_by()
        .values_list('ward_id', flat=True)
        .distinct()
    )
    wards = list(Ward.objects.filter(id__in=ward_ids).order_by('name').only('name', 'geometry'))
    pois_by_service = {
        service: list(
            PointOfInterest.objects
            .filter(inside_nairobi=True, major_category__in=config['major'])
            .order_by()
            .values('lat', 'lon')
        )
        for service, config in SERVICE_GAP_TARGETS.items()
    }
    rows = []
    for ward in wards:
        centroid = ward.geometry.centroid
        item = {'ward': ward.name}
        total_gap = 0
        available_services = 0
        for service, service_pois in pois_by_service.items():
            nearest = _nearest_distance_km(centroid.y, centroid.x, service_pois)
            item[f'{service.lower()}_km'] = nearest
            if nearest is not None:
                total_gap += min(nearest, 10)
                available_services += 1
        item['gap_score'] = round(total_gap / available_services, 2) if available_services else 0
        rows.append(item)

    rows = sorted(rows, key=lambda item: item['gap_score'], reverse=True)
    max_gap = max((item['gap_score'] for item in rows), default=1) or 1
    for item in rows:
        item['need_score'] = round(item['gap_score'] / max_gap * 100)
        item['main_gap'] = _main_service_gap(item)
        item['recommendation'] = _community_recommendation(item)
    return rows


def _main_service_gap(item):
    services = [
        ('Health', item.get('health_km')),
        ('Education', item.get('education_km')),
        ('Finance', item.get('finance_km')),
        ('Shopping', item.get('shopping_km')),
        ('Transport', item.get('transport_km')),
    ]
    services = [service for service in services if service[1] is not None]
    if not services:
        return 'No service data'
    name, distance = max(services, key=lambda service: service[1])
    return f'{name} access ({distance} km)'


def _community_recommendation(item):
    if item['need_score'] >= 75:
        return 'High priority for service investment and field validation.'
    if item['need_score'] >= 50:
        return 'Good candidate for targeted service improvement.'
    return 'Monitor service access and validate local demand.'


def _priority_actions(service_gaps):
    actions = []
    for item in service_gaps[:5]:
        actions.append({
            'ward': item['ward'],
            'action': f"Prioritize {item['main_gap'].lower()} and verify demand on the ground.",
            'score': item['need_score'],
        })
    return actions


def _essential_service_counts(pois):
    counts = {service: 0 for service in SERVICE_GAP_TARGETS}
    for poi in pois:
        major = _poi_get(poi, 'major_category')
        if major in counts:
            counts[major] += 1
    return [
        {
            'service': service,
            'label': SERVICE_GAP_TARGETS[service]['label'].title(),
            'count': count,
        }
        for service, count in counts.items()
    ]


def _community_ward_report(ward_name, service_gaps_all):
    if not ward_name:
        return None

    gap = next((item for item in service_gaps_all if item['ward'] == ward_name), None)
    pois, _ = _filtered_pois(ward=ward_name)
    counts = {
        item['major_category']: item['count']
        for item in pois.values('major_category').annotate(count=Count('id')).order_by('-count')
    }
    total = sum(counts.values())
    missing_services = []
    if gap:
        for service in ('health', 'education', 'finance', 'shopping', 'transport'):
            missing_services.append({
                'service': service.title(),
                'distance': gap.get(f'{service}_km'),
            })
        missing_services = sorted(
            missing_services,
            key=lambda item: item['distance'] if item['distance'] is not None else -1,
            reverse=True
        )

    return {
        'ward': ward_name,
        'total_pois': total,
        'counts': counts,
        'gap': gap,
        'missing_services': missing_services[:3],
        'recommendation': gap['recommendation'] if gap else 'Select another ward with available service data.',
    }


def _nearest_distance_km(lat, lon, pois):
    nearest = None
    for poi in pois:
        distance = _haversine_km(lat, lon, _poi_get(poi, 'lat'), _poi_get(poi, 'lon'))
        if nearest is None or distance < nearest:
            nearest = distance
    return round(nearest, 2) if nearest is not None else None


def _haversine_km(lat1, lon1, lat2, lon2):
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    return 6371 * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _category_quality_summary(pois):
    groups = defaultdict(lambda: {'total': 0, 'quality_total': 0, 'vague': 0})
    for poi in pois:
        group = groups[_poi_get(poi, 'major_category')]
        group['total'] += 1
        group['quality_total'] += _poi_quality_score(poi)
        if _is_vague_poi(poi):
            group['vague'] += 1

    rows = []
    for major_category, stats in groups.items():
        rows.append({
            'major_category': major_category,
            'total': stats['total'],
            'avg_quality': round(stats['quality_total'] / stats['total']) if stats['total'] else 0,
            'vague_share': round(stats['vague'] / stats['total'] * 100) if stats['total'] else 0,
        })
    return sorted(rows, key=lambda item: (item['avg_quality'], -item['total']))[:12]


def _cached_opportunity_scores(profile_key, profile):
    total_pois = PointOfInterest.objects.count()
    cache_key = f'opportunity_scores:v2:{profile_key}:{total_pois}'
    results = cache.get(cache_key)
    if results is None:
        results = _calculate_opportunity_scores(profile)
        cache.set(cache_key, results, 60 * 30)
    return results


def _calculate_opportunity_scores(profile):
    rows = (
        _clip_to_nairobi(PointOfInterest.objects)
        .values('ward_id', 'ward_name', 'major_category', 'category', 'data_source')
        .annotate(count=Count('id'))
    )
    ward_stats = defaultdict(lambda: {
        'ward': '',
        'total': 0,
        'target': 0,
        'demand': 0,
        'access': 0,
        'osm': 0,
        'local': 0,
    })

    target_categories = set(profile['target_categories'])
    target_major = set(profile['target_major'])
    demand_major = set(profile['demand_major'])
    access_major = set(profile['access_major'])

    for row in rows:
        stats = ward_stats[row['ward_id']]
        count = row['count']
        stats['ward'] = row['ward_name']
        stats['total'] += count
        if row['data_source'] == 'osm':
            stats['osm'] += count
        else:
            stats['local'] += count

        if row['category'] in target_categories or row['major_category'] in target_major:
            stats['target'] += count
        if row['major_category'] in demand_major:
            stats['demand'] += count
        if row['major_category'] in access_major:
            stats['access'] += count

    max_demand = max((item['demand'] for item in ward_stats.values()), default=1) or 1
    max_access = max((item['access'] for item in ward_stats.values()), default=1) or 1
    max_target = max((item['target'] for item in ward_stats.values()), default=1) or 1

    results = []
    for stats in ward_stats.values():
        demand_norm = stats['demand'] / max_demand
        access_norm = stats['access'] / max_access
        competition_norm = stats['target'] / max_target
        source_confidence = stats['osm'] / stats['total'] if stats['total'] else 0
        gap_score = max(0, demand_norm - competition_norm)
        score = (
            gap_score * 48
            + demand_norm * 24
            + access_norm * 18
            + source_confidence * 10
        )
        competition_label = 'Low'
        if competition_norm >= 0.66:
            competition_label = 'High'
        elif competition_norm >= 0.33:
            competition_label = 'Moderate'

        results.append({
            'ward': stats['ward'],
            'score': round(score, 1),
            'demand_score': round(demand_norm * 100),
            'competition_score': round(competition_norm * 100),
            'access_score': round(access_norm * 100),
            'target_count': stats['target'],
            'demand_count': stats['demand'],
            'access_count': stats['access'],
            'total_count': stats['total'],
            'osm_count': stats['osm'],
            'local_count': stats['local'],
            'source_confidence': round(source_confidence * 100),
            'competition_label': competition_label,
            'market_position': _market_position(demand_norm, competition_norm),
            'recommendation': _opportunity_recommendation(score, competition_label),
            'explanation': _score_explanation(stats['ward'], profile, demand_norm, competition_norm, access_norm, source_confidence),
        })

    return sorted(results, key=lambda item: item['score'], reverse=True)


def _opportunity_recommendation(score, competition_label):
    if score >= 70 and competition_label in ('Low', 'Moderate'):
        return 'Strong opportunity'
    if score >= 50:
        return 'Worth investigating'
    if competition_label == 'High':
        return 'Competitive area'
    return 'Lower priority'


def _market_position(demand_norm, competition_norm):
    if demand_norm >= 0.55 and competition_norm < 0.35:
        return 'Underserved high-demand area'
    if demand_norm >= 0.55 and competition_norm >= 0.35:
        return 'Busy but competitive area'
    if demand_norm < 0.55 and competition_norm < 0.35:
        return 'Emerging or low-coverage area'
    return 'Saturated low-demand area'


def _score_explanation(ward, profile, demand_norm, competition_norm, access_norm, source_confidence):
    demand = 'strong' if demand_norm >= 0.6 else 'moderate' if demand_norm >= 0.3 else 'limited'
    competition = 'low' if competition_norm < 0.35 else 'moderate' if competition_norm < 0.66 else 'high'
    access = 'good' if access_norm >= 0.5 else 'modest'
    confidence = 'high' if source_confidence >= 0.7 else 'mixed'
    return (
        f"{ward} shows {demand} demand signals for {profile['label'].lower()}, "
        f"{competition} existing competition, {access} access support, and {confidence} OSM/API data coverage."
    )


def _opportunity_geojson(results):
    ward_names = [item['ward'] for item in results]
    wards = {
        ward.name: ward
        for ward in Ward.objects.filter(name__in=ward_names)
    }
    features = []
    for item in results:
        ward = wards.get(item['ward'])
        if not ward:
            continue
        features.append({
            'type': 'Feature',
            'geometry': json.loads(ward.geometry.geojson),
            'properties': {
                'ward': item['ward'],
                'score': item['score'],
                'recommendation': item['recommendation'],
                'market_position': item['market_position'],
                'demand_score': item['demand_score'],
                'competition_score': item['competition_score'],
                'access_score': item['access_score'],
            },
        })
    return {'type': 'FeatureCollection', 'features': features}


@require_POST
def parse_query(request):
    """Parse natural language query and return filter suggestions"""
    if request.content_type == 'application/json':
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            payload = {}
        query = str(payload.get('query', '')).lower().strip()
    else:
        query = request.POST.get('query', '').lower().strip()

    suggestions = {
        'major_category': None,
        'category': None,
        'ward': None,
        'wants_near': False
    }

    # Parse major categories
    if any(word in query for word in ['church', 'churches', 'mosque', 'mosques', 'temple', 'religion', 'worship']):
        suggestions['major_category'] = 'Religion'
        suggestions['category'] = 'place_of_worship'
    elif any(word in query for word in ['restaurant', 'restaurants', 'food', 'cafe', 'cafes', 'bar', 'bars', 'pub', 'pubs']):
        suggestions['major_category'] = 'Food & Drink'
    elif any(word in query for word in ['hospital', 'clinic', 'pharmacy', 'doctor', 'health']):
        suggestions['major_category'] = 'Health'
    elif any(word in query for word in ['school', 'schools', 'college', 'university', 'education']):
        suggestions['major_category'] = 'Education'
    elif any(word in query for word in ['hotel', 'hotels', 'guest house', 'hostel', 'accommodation']):
        suggestions['major_category'] = 'Accommodation'
    elif any(word in query for word in ['bank', 'atm', 'finance']):
        suggestions['major_category'] = 'Finance'
    elif any(word in query for word in ['fuel', 'petrol', 'gas station', 'transport']):
        suggestions['major_category'] = 'Transport'
    elif any(word in query for word in ['shop', 'shopping', 'supermarket', 'market']):
        suggestions['major_category'] = 'Shopping'

    # Check for "near me" or similar
    if any(phrase in query for phrase in ['close to me', 'near me', 'closest', 'nearby']):
        suggestions['wants_near'] = True

    # Try to find ward matches
    wards = list(
        Ward.objects.filter(pois__isnull=False)
        .distinct()
        .values_list('name', flat=True)
    )
    wards.sort(key=len, reverse=True)
    for ward in wards:
        ward_pattern = r'(?<!\w)' + re.escape(ward.lower()) + r'(?!\w)'
        if re.search(ward_pattern, query):
            suggestions['ward'] = ward
            break

    return JsonResponse(suggestions)
