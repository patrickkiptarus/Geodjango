#!/usr/bin/env python3
"""
Test script to verify Django setup and data loading
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nairobi_location_intelligence.settings')
django.setup()

from location_intelligence.models import PointOfInterest, Ward

def test_database():
    """Test database connection and models"""
    print("Testing database connection...")

    try:
        # Test ward count
        ward_count = Ward.objects.count()
        print(f"✓ Found {ward_count} wards in database")

        # Test POI count
        poi_count = PointOfInterest.objects.count()
        print(f"✓ Found {poi_count} POIs in database")

        if poi_count > 0:
            # Test a sample query
            sample_poi = PointOfInterest.objects.first()
            print(f"✓ Sample POI: {sample_poi.name} in {sample_poi.ward_name}")

            # Test filtering
            restaurants = PointOfInterest.objects.filter(major_category='Food & Drink').count()
            print(f"✓ Found {restaurants} food & drink establishments")

        return True

    except Exception as e:
        print(f"✗ Database test failed: {e}")
        return False

def test_views():
    """Test that views can be imported"""
    print("Testing view imports...")

    try:
        from location_intelligence import views
        print("✓ Views imported successfully")
        return True
    except Exception as e:
        print(f"✗ View import failed: {e}")
        return False

def main():
    print("Django Nairobi Location Intelligence - Test Suite")
    print("=" * 50)

    success = True

    success &= test_views()
    success &= test_database()

    print("=" * 50)
    if success:
        print("✓ All tests passed! Ready to run the application.")
        print("Run: python manage.py runserver")
    else:
        print("✗ Some tests failed. Please check your setup.")

if __name__ == "__main__":
    main()