import streamlit as st
import geopandas as gpd
import rasterio
import numpy as np
from shapely.geometry import LineString
import ezdxf
import pandas as pd
import tempfile
import os
from io import BytesIO

# Set page configuration
st.set_page_config(
    page_title="Haul Road Gradient Analysis",
    page_icon="🛣️",
    layout="wide"
)

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

def process_haul_road(shapefile_path, dtm_path, segment_length, attribute_field=None):
    gdf, lines = process_shapefile(shapefile_path)
    total_length = 0
    green_length = 0
    red_length = 0
    detailed_results = []

    with rasterio.open(dtm_path) as dtm:
        doc = ezdxf.new(dxfversion='R2010')
        msp = doc.modelspace()

        for idx, line in enumerate(lines):
            points, slopes = calculate_slope_fraction(line, dtm, segment_length)
            attr_value = None
            if attribute_field and attribute_field in gdf.columns:
                attr_value = gdf.iloc[idx][attribute_field]

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
                    'Attribute': attr_value if attr_value else 'N/A',
                    'Length (m)': round(segment_length_meters, 2),
                    'Slope Ratio': round(slope_ratio, 4),
                    'Slope Fraction': slope_to_fraction(slope_ratio),
                    'Status': status
                })

                # Add DXF elements
                points_coords = list(segment.coords)
                msp.add_lwpolyline(points_coords, dxfattribs={'color': color})
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
        'Length (meters)': [
            round(total_length, 2),
            round(green_length, 2),
            round(red_length, 2)
        ],
        'Percentage': [
            100.0,
            round((green_length/total_length)*100, 2) if total_length > 0 else 0,
            round((red_length/total_length)*100, 2) if total_length > 0 else 0
        ]
    }
    summary_df = pd.DataFrame(summary_data)
    detailed_df = pd.DataFrame(detailed_results)
    return dxf_buffer, summary_df, detailed_df

# --- Streamlit UI ---
st.title("🛣️ Haul Road Gradient Analysis")
st.markdown("---")

# Sidebar inputs
st.sidebar.header("Input Parameters")

uploaded_shapefile = st.sidebar.file_uploader("Upload Shapefile (.shp)", type=['shp'])
uploaded_shx = st.sidebar.file_uploader("Upload .shx file", type=['shx'])
uploaded_dbf = st.sidebar.file_uploader("Upload .dbf file", type=['dbf'])
uploaded_prj = st.sidebar.file_uploader("Upload .prj file (optional)", type=['prj'])

# Local DTM path input
dtm_path = st.sidebar.text_input(
    "Enter Local DTM File Path (.tif)",
    value=r"D:\Haul Road\DTM\your_large_dtm.tif",
    help="Provide the full path to the DTM file on the server or local machine."
)

segment_length = st.sidebar.number_input("Sampling Interval (meters)", min_value=1, max_value=100, value=25, step=1)

attribute_field = None
if uploaded_shapefile and uploaded_shx and uploaded_dbf:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            shp_path = os.path.join(tmpdir, "input.shp")
            shx_path = os.path.join(tmpdir, "input.shx")
            dbf_path = os.path.join(tmpdir, "input.dbf")
            with open(shp_path, 'wb') as f:
                f.write(uploaded_shapefile.read())
            with open(shx_path, 'wb') as f:
                f.write(uploaded_shx.read())
            with open(dbf_path, 'wb') as f:
                f.write(uploaded_dbf.read())
            if uploaded_prj:
                prj_path = os.path.join(tmpdir, "input.prj")
                with open(prj_path, 'wb') as f:
                    f.write(uploaded_prj.read())
            gdf = gpd.read_file(shp_path)
            attribute_fields = ['None'] + list(gdf.columns[gdf.columns != 'geometry'])
            attribute_field = st.sidebar.selectbox("Attribute Field (optional)", options=attribute_fields)
            if attribute_field == 'None':
                attribute_field = None
    except Exception as e:
        st.sidebar.warning(f"Could not read shapefile attributes: {str(e)}")

st.sidebar.markdown("---")
analyze_button = st.sidebar.button("🚀 Run Analysis", type="primary")

# Analysis
if analyze_button:
    if not all([uploaded_shapefile, uploaded_shx, uploaded_dbf]) or not dtm_path:
        st.error("⚠️ Please upload shapefile components and enter DTM path!")
    else:
        try:
            with st.spinner("Processing haul road gradient analysis..."):
                with tempfile.TemporaryDirectory() as tmpdir:
                    shp_path = os.path.join(tmpdir, "input.shp")
                    shx_path = os.path.join(tmpdir, "input.shx")
                    dbf_path = os.path.join(tmpdir, "input.dbf")
                    with open(shp_path, 'wb') as f:
                        f.write(uploaded_shapefile.read())
                    with open(shx_path, 'wb') as f:
                        f.write(uploaded_shx.read())
                    with open(dbf_path, 'wb') as f:
                        f.write(uploaded_dbf.read())
                    if uploaded_prj:
                        prj_path = os.path.join(tmpdir, "input.prj")
                        with open(prj_path, 'wb') as f:
                            f.write(uploaded_prj.read())

                    dxf_buffer, summary_df, detailed_df = process_haul_road(shp_path, dtm_path, segment_length, attribute_field)

                    st.success("✅ Analysis completed successfully!")
                    st.subheader("📊 Summary Results")
                    st.dataframe(summary_df, width='stretch', hide_index=True)

                    st.subheader("📋 Detailed Segment Analysis")
                    st.dataframe(detailed_df, width='stretch', hide_index=True)

                    st.subheader("⬇️ Download Results")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.download_button("📥 Download DXF", data=dxf_buffer, file_name="haul_road_gradient.dxf", mime="application/dxf")
                    with col2:
                        summary_excel = BytesIO()
                        summary_df.to_excel(summary_excel, index=False, sheet_name='Summary')
                        summary_excel.seek(0)
                        st.download_button("📥 Download Summary (Excel)", data=summary_excel, file_name="haul_road_summary.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    with col3:
                        detailed_excel = BytesIO()
                        detailed_df.to_excel(detailed_excel, index=False, sheet_name='Detailed Analysis')
                        detailed_excel.seek(0)
                        st.download_button("📥 Download Detailed (Excel)", data=detailed_excel, file_name="haul_road_detailed.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.error(f"❌ Error during analysis: {str(e)}")
            st.exception(e)
