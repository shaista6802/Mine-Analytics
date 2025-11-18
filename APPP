import streamlit as st
import geopandas as gpd
import rasterio
import numpy as np
from shapely.geometry import LineString
import ezdxf
import pandas as pd
import os


# --- Core Functions ---
def get_elevation(point, dtm):
    x, y = point.x, point.y
    row, col = dtm.index(x, y)
    elevation = dtm.read(1)[row, col]
    return elevation

def calculate_slope_fraction(line, dtm, segment_length):
    length = line.length
    slopes = []
    points = []
    distances = np.arange(0, length, segment_length)
    if distances[-1] < length:
        distances = np.append(distances, length)
    elevations = []
    for dist in distances:
        point = line.interpolate(dist)
        points.append(point)
        elevation = get_elevation(point, dtm)
        elevations.append(elevation)
    for i in range(1, len(points)):
        dx = points[i].distance(points[i-1])
        dz = elevations[i] - elevations[i-1]
        slope_ratio = dz/dx if dx != 0 else 0
        slopes.append(slope_ratio)
    return points, slopes

def slope_to_fraction(slope_ratio):
    if slope_ratio == 0:
        return "Flat"
    fraction = 1 / abs(slope_ratio)
    return f"1/{fraction:.2f}"

def slope_to_color(slope_ratio):
    if -1/16 <= slope_ratio <= 1/16:
        return 3  # Green
    else:
        return 1  # Red

def process_shapefile(shapefile_path):
    gdf = gpd.read_file(shapefile_path)
    return [geom for geom in gdf.geometry if isinstance(geom, LineString)]

def Process_shapefile_to_dxf_hatch(input_shapefile, dtm_file, output_dxf, output_excel, segment_length=25):
    lines = process_shapefile(input_shapefile)
    total_length = green_length = yellow_length = red_length = 0

    with rasterio.open(dtm_file) as dtm:
        doc = ezdxf.new(dxfversion='R2010')
        msp = doc.modelspace()

        for line in lines:
            points, slopes = calculate_slope_fraction(line, dtm, segment_length)
            for i in range(len(points) - 1):
                segment = LineString([points[i], points[i+1]])
                slope_ratio = slopes[i]
                color = slope_to_color(slope_ratio)
                segment_length_meters = segment.length
                total_length += segment_length_meters
                if color == 3:
                    green_length += segment_length_meters
                elif color == 2:
                    yellow_length += segment_length_meters
                else:
                    red_length += segment_length_meters
                msp.add_lwpolyline(list(segment.coords), dxfattribs={'color': color})
                buffer_polygon = segment.buffer(5, cap_style='flat')
                hatch = msp.add_hatch(color=color)
                hatch.paths.add_polyline_path(buffer_polygon.exterior.coords)
                midpoint = segment.interpolate(0.5, normalized=True)
                slope_fraction = slope_to_fraction(slope_ratio)
                msp.add_text(f"{slope_fraction}", dxfattribs={'height': 4, 'color': 7}).set_dxf_attrib('insert', (midpoint.x, midpoint.y))

        doc.saveas(output_dxf)
        df = pd.DataFrame({
            'Total Length (meters)': [total_length],
            'Green': [green_length],
            'Yellow': [yellow_length],
            'Red': [red_length]
        })
        df.to_excel(output_excel, index=False)

# --- Streamlit UI ---
st.title("Haul Road Gradient Analysis Tool")

shapefile_path = st.text_input("Enter path to Shapefile (.shp)")
#dtm_path = st.text_input("Enter path to DTM Raster (.tif)")
st.markdown("### Enter path to DTM Raster (.tif)")
dtm_path = st.text_input("DTM file path", value=r"D:\your\path\to\DTM.tif")
segment_length = st.number_input("Segment Length (meters)", min_value=1, value=25)

output_dxf = st.text_input("Output DXF file path", value="output_gradient.dxf")
output_excel = st.text_input("Output Excel file path", value="output_gradient.xlsx")

if st.button("Run Gradient Analysis"):
    if os.path.exists(shapefile_path) and os.path.exists(dtm_path):
        Process_shapefile_to_dxf_hatch(shapefile_path, dtm_path, output_dxf, output_excel, segment_length)
        st.success("Processing complete!")
        st.write("Download your results:")
        st.download_button("Download DXF", data=open(output_dxf, "rb").read(), file_name=os.path.basename(output_dxf))
        st.download_button("Download Excel", data=open(output_excel, "rb").read(), file_name=os.path.basename(output_excel))
    else:
        st.error("Please check the file paths. One or both files do not exist.")
