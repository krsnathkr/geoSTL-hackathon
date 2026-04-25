"""
Fetch Overture Maps Places and transportation features for the SF bbox via DuckDB.

Outputs:
  data/raw/overture_places.parquet
  data/raw/overture_transport.parquet
"""

import logging
import os

import duckdb
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

from config.settings import (
    BBOX,
    DATA_RAW,
    OVERTURE_S3_BASE,
    WGS84_CRS,
)

logger = logging.getLogger(__name__)


def _get_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("SET s3_region='us-east-1';")
    return con


def fetch_places(output_dir: str = DATA_RAW) -> gpd.GeoDataFrame:
    """Query Overture Places for the configured SF bbox and write to parquet."""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "overture_places.parquet")

    con = _get_con()
    s3_glob = f"{OVERTURE_S3_BASE}/theme=places/type=place/*"

    query = f"""
        SELECT
            id,
            names.primary           AS name,
            categories.primary      AS category,
            confidence,
            geometry,
            bbox.xmin               AS lon,
            bbox.ymin               AS lat,
            addresses,
            sources
        FROM read_parquet('{s3_glob}', hive_partitioning=1)
        WHERE bbox.xmin BETWEEN {BBOX['min_lon']} AND {BBOX['max_lon']}
          AND bbox.ymin BETWEEN {BBOX['min_lat']} AND {BBOX['max_lat']}
    """

    logger.info("Querying Overture Places for SF bbox…")
    df = con.execute(query).df()
    logger.info("Retrieved %d places", len(df))

    gdf = _df_to_gdf(df)
    gdf.to_parquet(out_path, index=False)
    logger.info("Saved → %s", out_path)
    return gdf


def fetch_transportation(output_dir: str = DATA_RAW) -> gpd.GeoDataFrame:
    """Query Overture transportation segments for the configured SF bbox."""
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "overture_transport.parquet")

    con = _get_con()
    s3_glob = f"{OVERTURE_S3_BASE}/theme=transportation/type=segment/*"

    query = f"""
        SELECT
            id,
            subtype,
            class,
            names.primary           AS name,
            road,
            geometry,
            bbox.xmin               AS lon_min,
            bbox.ymin               AS lat_min,
            bbox.xmax               AS lon_max,
            bbox.ymax               AS lat_max,
            sources
        FROM read_parquet('{s3_glob}', hive_partitioning=1)
        WHERE bbox.xmin BETWEEN {BBOX['min_lon']} AND {BBOX['max_lon']}
          AND bbox.ymin BETWEEN {BBOX['min_lat']} AND {BBOX['max_lat']}
    """

    logger.info("Querying Overture transportation for SF bbox…")
    df = con.execute(query).df()
    logger.info("Retrieved %d segments", len(df))

    gdf = _df_to_gdf(df)
    gdf.to_parquet(out_path, index=False)
    logger.info("Saved → %s", out_path)
    return gdf


def load_places(data_dir: str = DATA_RAW) -> gpd.GeoDataFrame:
    """Load previously fetched places parquet without re-querying S3."""
    path = os.path.join(data_dir, "overture_places.parquet")
    return gpd.read_parquet(path)


def load_transportation(data_dir: str = DATA_RAW) -> gpd.GeoDataFrame:
    """Load previously fetched transportation parquet without re-querying S3."""
    path = os.path.join(data_dir, "overture_transport.parquet")
    return gpd.read_parquet(path)


def _df_to_gdf(df: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convert a DataFrame with a WKB/WKT 'geometry' column to a GeoDataFrame."""
    if df.empty:
        return gpd.GeoDataFrame(df, geometry=gpd.GeoSeries([], crs=WGS84_CRS))

    geom_col = df["geometry"]

    # Overture returns geometry as WKB bytes or GeoJSON-like structs
    if hasattr(geom_col.iloc[0], "__geo_interface__"):
        geoms = gpd.GeoSeries(geom_col.apply(shape), name="geometry", crs=WGS84_CRS)
    else:
        from shapely import wkb
        geoms = gpd.GeoSeries(
            geom_col.apply(lambda g: wkb.loads(bytes(g) if isinstance(g, memoryview) else g)),
            name="geometry",
            crs=WGS84_CRS,
        )

    # Drop raw bytes column, then attach parsed geometries
    df_clean = df.drop(columns=["geometry"])
    return gpd.GeoDataFrame(df_clean, geometry=geoms, crs=WGS84_CRS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    places = fetch_places()
    print(f"Places: {len(places)} rows, columns: {list(places.columns)}")
    transport = fetch_transportation()
    print(f"Transport: {len(transport)} rows, columns: {list(transport.columns)}")
