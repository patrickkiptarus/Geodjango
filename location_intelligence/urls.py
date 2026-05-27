from django.urls import path
from . import views

app_name = 'location_intelligence'

urlpatterns = [
    path('', views.index, name='index'),
    path('map/', views.map_explorer, name='map_explorer'),
    path('places/', views.place_results, name='place_results'),
    path('insights/', views.business_insights, name='business_insights'),
    path('opportunities/', views.opportunity_analysis, name='opportunity_analysis'),
    path('community/', views.data_science_insights, name='community_needs'),
    path('data-science/', views.data_science_insights, name='data_science_insights'),
    path('api/map-pois/', views.map_pois, name='map_pois'),
    path('api/map-boundaries/', views.map_boundaries, name='map_boundaries'),
    path('api/find-nearest/', views.find_nearest, name='find_nearest'),
    path('api/parse-query/', views.parse_query, name='parse_query'),
]
