# Nairobi Location Intelligence System - Django

This is a Django web application that replicates the functionality of the original Shiny R application for Nairobi Location Intelligence. It provides interactive mapping, filtering, and analysis of Points of Interest (POIs) in Nairobi.

## Features

- **Interactive Map Explorer**: Filter POIs by category, ward, and name with Leaflet mapping
- **Place Results Table**: DataTables-powered table of filtered results
- **Nearest Places Finder**: Calculate and display nearest POIs from a given location
- **Business Insights**: Visual analysis with plots and summaries
- **Smart Search**: Natural language query parsing
- **Dark Theme**: Modern dark UI matching the original Shiny app

## Setup Instructions

### 1. Prerequisites

- Python 3.8+
- PostgreSQL with PostGIS extension
- Git

### 2. Database Setup

Create a PostgreSQL database with PostGIS:

```sql
CREATE DATABASE nairobi_location_intelligence;
CREATE EXTENSION postgis;
```

Copy `.env.example` to `.env`, then set `POSTGRES_PASSWORD` to the password for your local PostgreSQL user:

```env
POSTGRES_DB=nairobi_location_intelligence
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### 3. Installation

1. Clone or copy this project to your local machine
2. Navigate to the project directory
3. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Run migrations:
   ```bash
   python manage.py migrate
   ```

### 4. Data Loading

The application expects POI and ward boundary data. You'll need to prepare the data from the original Shiny app:

1. Run the `prepare_data.R` script from the original project to generate `data/poi_nairobi.rds`
2. Convert the RDS file to CSV format (you can use R or Python for this)
3. Load the data using the management command:
   ```bash
   python manage.py load_data --data-dir ../data
   ```

### 5. Run the Application

```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000` in your browser.

## Project Structure

```
nairobi_location_intelligence/
├── nairobi_location_intelligence/  # Main project settings
├── location_intelligence/          # Main app
│   ├── models.py                   # POI and Ward models
│   ├── views.py                    # View functions
│   ├── urls.py                     # URL routing
│   ├── admin.py                    # Django admin configuration
│   └── management/commands/        # Management commands
├── templates/                      # HTML templates
├── static/                         # Static files (CSS, JS)
├── requirements.txt                # Python dependencies
└── manage.py                       # Django management script
```

## Key Components

### Models

- **PointOfInterest**: Stores POI data with spatial location
- **Ward**: Stores Nairobi ward boundaries as polygons

### Views

- `map_explorer`: Main map view with filtering
- `place_results`: Data table view
- `business_insights`: Analytics and plotting
- `find_nearest`: AJAX endpoint for nearest places
- `parse_query`: Natural language query parsing

### Features Replicated

1. **Filtering**: By major category, specific category, ward, and name search
2. **Mapping**: Leaflet-based interactive map with clustering
3. **Geolocation**: Browser geolocation support
4. **Nearest Places**: Haversine distance calculation
5. **Smart Search**: Keyword-based natural language parsing
6. **Data Visualization**: Plotly.js charts for insights
7. **Dark Theme**: Bootstrap-based dark UI

## API Endpoints

- `GET /`: Main map explorer
- `GET /places/`: Place results table
- `GET /insights/`: Business insights
- `POST /api/find-nearest/`: Find nearest places (AJAX)
- `POST /api/parse-query/`: Parse natural language queries (AJAX)

## Technologies Used

- **Backend**: Django 4.2, PostgreSQL + PostGIS
- **Frontend**: Bootstrap 5, Leaflet, DataTables, Plotly.js
- **Spatial**: GeoDjango, GeoPandas
- **Styling**: Custom dark theme CSS

## Performance Considerations

- Spatial indexes on location fields
- Database-level filtering and aggregation
- Limited POI rendering on map (max 1000 points)
- Efficient distance calculations using PostGIS functions

## Deployment

For production deployment:

1. Set `DEBUG = False` in settings
2. Configure proper database credentials
3. Set up static file serving
4. Configure web server (nginx + gunicorn recommended)
5. Set up HTTPS
6. Configure proper logging and monitoring

## License

This project is provided as-is for educational and demonstration purposes.
