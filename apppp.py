import streamlit as st
import geopandas as gpd
import rasterio
import numpy as np
from shapely.geometry import LineString
import ezdxf
import pandas as pd
import tempfile
import zipfile
import os
from io import BytesIO

st.set_page_config(page_title="Haul Road Gradient Analysis", page_icon="🛣️", layout="wide")

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
    return gdf, [geom for geom in gdf.geometry if isinstance(geom, LineString)]

def process_haul_road(shapefile_path, dtm_path, segment_length):
    gdf, lines = process_shapefile(shapefile_path)
    total_length = green_length = red_length = 0
    detailed_results = []

    with rasterio.open(dtm_path) as dtm:
        doc = ezdxf.new(dxfversion='R2010')
        msp = doc.modelspace()

        for idx, line in enumerate(lines):
            points, slopes = calculate_slope_fraction(line, dtm, segment_length)
            for i in range(len(points) - 1):
                segment = LineString([points[i], points[i+1]])
                slope_ratio = slopes[i]
                color = slope_to_color(slope_ratio)
                segment_length_meters = segment.length
                total_length += segment_length_meters
                if color == 3:
                    green_length += segment_length_meters
                    status = "Acceptable"
                else:
                    red_length += segment_length_meters
                    status = "Steep"

                detailed_results.append({
                    'Segment': f"{idx+1}-{i+1}",
                    'Length (m)': round(segment_length_meters, 2),
                    'Slope Ratio': round(slope_ratio, 4),
                    'Slope Fraction': slope_to_fraction(slope_ratio),
                    'Status': status
                })

                # DXF elements
                msp.add_lwpolyline(list(segment.coords), dxfattribs={'color': color})
                buffer_polygon = segment.buffer(5, cap_style='flat')
                hatch = msp.add_hatch(color=color)
                hatch.paths.add_polyline_path(buffer_polygon.exterior.coords)
                midpoint = segment.interpolate(0.5, normalized=True)
                msp.add_text(f"{slope_to_fraction(slope_ratio)}",
                             dxfattribs={'height': 4, 'color': 7}).set_dxf_attrib('insert', (midpoint.x, midpoint.y))

        # Save DXF to buffer
        dxf_buffer = BytesIO()
        with tempfile.NamedTemporaryFile(delete=False, suffix='.dxf') as tmp:
            doc.saveas(tmp.name)
            with open(tmp.name, 'rb') as f:
                dxf_buffer.write(f.read())
            os.unlink(tmp.name)
        dxf_buffer.seek(0)

    summary_data = {
        'Category': ['Total Length', 'Green (Acceptable)', 'Red (Steep)'],
        'Length (meters)': [round(total_length, 2), round(green_length, 2), round(red_length, 2)],
        'Percentage': [
            100.0,
            round((green_length/total_length)*100, 2) if total_length > 0 else 0,
            round((red_length/total_length)*100, 2) if total_length > 0 else 0
        ]
    }
    return dxf_buffer, pd.DataFrame(summary_data), pd.DataFrame(detailed_results)

# --- Streamlit UI ---
st.title("🛣️ Haul Road Gradient Analysis")
st.markdown("---")

# Upload shapefile ZIP
shapefile_zip = st.file_uploader("Upload Shapefile ZIP (.zip)", type=["zip"])
dtm_path = st.text_input("Enter Local DTM File Path (.tif)", value=r"D:\Haul Road\DTM\your_large_dtm.tif")
segment_length = st.number_input("Segment Length (meters)", min_value=1, value=25)

if st.button("🚀 Run Analysis"):
    if not shapefile_zip or not dtm_path:
        st.error("Please upload shapefile ZIP and enter DTM path!")
    else:
        try:
            with st.spinner("Processing..."):
                with tempfile.TemporaryDirectory() as tmpdir:
                    # Extract ZIP
                    zip_path = os.path.join(tmpdir, "shapefile.zip")
                    with open(zip_path, "wb") as f:
                        f.write(shapefile_zip.read())
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(tmpdir)

                    # Find .shp file
                    shp_files = [f for f in os.listdir(tmpdir) if f.endswith(".shp")]
                    if not shp_files:
                        st.error("No .shp file found in ZIP!")
                    else:
                        shp_path = os.path.join(tmpdir, shp_files[0])
                        dxf_buffer, summary_df, detailed_df = process_haul_road(shp_path, dtm_path, segment_length)

                        st.success("✅ Analysis completed!")
                        st.subheader("📊 Summary")
                        st.dataframe(summary_df)
                        st.subheader("📋 Detailed Analysis")
                        st.dataframe(detailed_df)

                        st.download_button("📥 Download DXF", data=dxf_buffer, file_name="haul_road_gradient.dxf", mime="application/dxf")
                        excel_summary = BytesIO()
                        summary_df.to_excel(excel_summary, index=False)
                        excel_summary.seek(0)
                        st.download_button("📥 Download Summary (Excel)", data=excel_summary, file_name="summary.xlsx")
                        excel_detailed = BytesIO()
                        detailed_df.to_excel(excel_detailed, index=False)
                        excel_detailed.seek(0)
                        st.download_button("📥 Download Detailed (Excel)", data=excel_detailed, file_name="detailed.xlsx")
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.exception(e)
