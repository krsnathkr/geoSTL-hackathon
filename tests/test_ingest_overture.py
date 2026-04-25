"""Unit tests for ingest/overture.py — mocks DuckDB so no S3 access needed."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from ingest.overture import _df_to_gdf, fetch_places, fetch_transportation


def _make_mock_df():
    """Minimal DataFrame matching the Overture Places query shape."""
    geom = Point(-122.42, 37.77)
    return pd.DataFrame(
        [
            {
                "id": "gers-001",
                "name": "Blue Bottle Coffee",
                "category": "coffee_shop",
                "confidence": 0.95,
                "geometry": geom.wkb,
                "lon": -122.42,
                "lat": 37.77,
                "addresses": None,
                "sources": None,
            }
        ]
    )


def test_df_to_gdf_with_wkb():
    df = _make_mock_df()
    gdf = _df_to_gdf(df)
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert gdf.crs.to_epsg() == 4326
    assert len(gdf) == 1
    assert gdf.iloc[0].geometry.x == pytest.approx(-122.42)


def test_df_to_gdf_empty():
    df = pd.DataFrame(columns=["id", "name", "geometry"])
    gdf = _df_to_gdf(df)
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == 0


@patch("ingest.overture._get_con")
def test_fetch_places_creates_parquet(mock_get_con):
    mock_con = MagicMock()
    mock_get_con.return_value = mock_con
    mock_con.execute.return_value.df.return_value = _make_mock_df()

    with tempfile.TemporaryDirectory() as tmp:
        gdf = fetch_places(output_dir=tmp)
        assert os.path.exists(os.path.join(tmp, "overture_places.parquet"))
        assert len(gdf) == 1
        assert gdf.iloc[0]["name"] == "Blue Bottle Coffee"


@patch("ingest.overture._get_con")
def test_fetch_transportation_creates_parquet(mock_get_con):
    mock_con = MagicMock()
    mock_get_con.return_value = mock_con
    transport_df = pd.DataFrame(
        [
            {
                "id": "seg-001",
                "subtype": "road",
                "class": "primary",
                "name": "Market St",
                "road": None,
                "geometry": Point(-122.41, 37.78).wkb,
                "lon_min": -122.41,
                "lat_min": 37.78,
                "lon_max": -122.40,
                "lat_max": 37.79,
                "sources": None,
            }
        ]
    )
    mock_con.execute.return_value.df.return_value = transport_df

    with tempfile.TemporaryDirectory() as tmp:
        gdf = fetch_transportation(output_dir=tmp)
        assert os.path.exists(os.path.join(tmp, "overture_transport.parquet"))
        assert len(gdf) == 1
        assert gdf.iloc[0]["name"] == "Market St"
