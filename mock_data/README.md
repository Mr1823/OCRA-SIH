# Mock Data — ORCA Marine Conditions

Sample JSON files providing realistic marine/weather data for Indian coastal cities.
These files serve as a reliable fallback when live API access is unavailable.

## Files

| File | Location | Scenario |
|---|---|---|
| `chennai.json` | Chennai, Tamil Nadu | ✅ Safe — calm seas, nearby PFZ, no alerts |
| `visakhapatnam.json` | Visakhapatnam, Andhra Pradesh | 🔴 Unsafe — active cyclone, high waves |
| `mumbai.json` | Mumbai, Maharashtra | 🟡 Caution — moderate waves, lightning alert |

## Schema

```jsonc
{
  "location": {
    "name": "string",          // Display name
    "lat": 0.0,                // Latitude (decimal degrees)
    "lon": 0.0,                // Longitude (decimal degrees)
    "region": "string"         // State / region
  },
  "timestamp": "ISO-8601",     // Query reference time
  "data_timestamp": "ISO-8601",// When source data was last updated

  "ocean": {
    "sst": 0.0,                // Sea Surface Temperature (°C)
    "chlorophyll": 0.0,        // Chlorophyll concentration (mg/m³)
    "wave_height": 0.0,        // Significant wave height (m)
    "wave_period": 0.0         // Dominant wave period (s)
  },

  "weather": {
    "wind_speed": 0.0,         // Wind speed (km/h)
    "wind_direction": "SW",    // Cardinal/intercardinal
    "visibility": 0.0,         // Visibility (km)
    "temperature": 0.0,        // Air temperature (°C)
    "humidity": 0,             // Relative humidity (%)
    "condition": "string"      // Human-readable summary
  },

  "tide": {
    "current": "high|low",
    "next_change": "HH:MM",
    "next_type": "high|low",
    "tidal_range_m": 0.0
  },

  "alerts": [                  // Empty array = no alerts
    {
      "type": "cyclone|lightning|high_wave",
      "severity": "watch|warning|alert",
      "title": "string",
      "message": "string",
      "issued_at": "ISO-8601",
      "valid_until": "ISO-8601",
      "source": "IMD|INCOIS"
    }
  ],

  "pfz_zones": [               // Empty array = no nearby PFZ
    {
      "id": "string",
      "lat": 0.0,
      "lon": 0.0,
      "distance_km": 0.0,
      "confidence": "high|medium|low",
      "sst": 0.0,
      "chlorophyll": 0.0,
      "species_likely": ["string"],
      "valid_until": "ISO-8601"
    }
  ]
}
```

## Adding New Locations

1. Copy an existing file and rename it to `<city>.json`
2. Update `location`, `ocean`, `weather`, `tide`, `alerts`, and `pfz_zones`
3. The mock provider resolves queries to the nearest file by lat/lon

