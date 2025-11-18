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
        if dx != 0:
            slope_ratio = dz/dx
        else:
            slope_ratio = 0
        slopes.append(slope_ratio)
       
    return points, slopes

def slope_to_fraction(slope_ratio):
    if slope_ratio == 0:
        return "Flat"
    if slope_ratio > 0:
        fraction = 1 / slope_ratio
    else:
        fraction = -1 / slope_ratio
    return f"1/{abs(fraction):.2f}"

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
    
    with rasterio.open(dtm_path) as dtm:
        doc = ezdxf.new(dxfversion='R2010')
        msp = doc.modelspace()
        
        detailed_results = []
        
        for idx, line in enumerate(lines):
            points, slopes = calculate_slope_fraction(line, dtm, segment_length)
            
            # Get attribute value if field is specified
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
                
                # Add to detailed results
                detailed_results.append({
                    'Segment': f"{idx+1}-{i+1}",
                    'Attribute': attr_value if attr_value else 'N/A',
                    'Length (m)': round(segment_length_meters, 2),
                    'Slope Ratio': round(slope_ratio, 4),
                    'Slope Fraction': slope_to_fraction(slope_ratio),
                    'Status': status
                })
                
                points_coords = list(segment.coords)
                msp.add_lwpolyline(points_coords, dxfattribs={'color': color})
                
                buffer_polygon = segment.buffer(5, cap_style='flat')
                hatch = msp.add_hatch(color=color)
                hatch.paths.add_polyline_path(buffer_polygon.exterior.coords)
                
                slope_fraction = slope_to_fraction(slope_ratio)
                midpoint = segment.interpolate(0.5, normalized=True)
                msp.add_text(
                    f"{slope_fraction}", 
                    dxfattribs={'height': 4, 'color': 7}
                ).set_dxf_attrib('insert', (midpoint.x, midpoint.y))
        
        # Save DXF to bytes
        dxf_buffer = BytesIO()
        with tempfile.NamedTemporaryFile(delete=False, suffix='.dxf') as tmp:
            doc.saveas(tmp.name)
            with open(tmp.name, 'rb') as f:
                dxf_buffer.write(f.read())
            os.unlink(tmp.name)
        dxf_buffer.seek(0)
        
        # Create summary DataFrame
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

# Streamlit UI
st.title("🛣️ Haul Road Gradient Analysis")
st.markdown("---")

# Sidebar for inputs
st.sidebar.header("Input Parameters")

# File uploaders
uploaded_shapefile = st.sidebar.file_uploader(
    "Upload Shapefile (.shp)", 
    type=['shp'],
    help="Upload the main .shp file. Ensure .shx, .dbf files are uploaded too."
)

uploaded_shx = st.sidebar.file_uploader("Upload .shx file", type=['shx'])
uploaded_dbf = st.sidebar.file_uploader("Upload .dbf file", type=['dbf'])
uploaded_prj = st.sidebar.file_uploader("Upload .prj file (optional)", type=['prj'])

uploaded_dtm = st.sidebar.file_uploader(
    "Upload DTM File (.tif)", 
    type=['tif', 'tiff'],
    help="Upload Digital Terrain Model in TIFF format"
)

segment_length = st.sidebar.number_input(
    "Sampling Interval (meters)",
    min_value=1,
    max_value=100,
    value=25,
    step=1,
    help="Distance interval for slope calculation"
)

# Attribute field selection
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
            
            attribute_field = st.sidebar.selectbox(
                "Attribute Field (optional)",
                options=attribute_fields,
                help="Select an attribute field to include in the analysis"
            )
            
            if attribute_field == 'None':
                attribute_field = None
                
            # Reset file pointers
            uploaded_shapefile.seek(0)
            uploaded_shx.seek(0)
            uploaded_dbf.seek(0)
            if uploaded_prj:
                uploaded_prj.seek(0)
    except Exception as e:
        st.sidebar.warning(f"Could not read shapefile attributes: {str(e)}")

st.sidebar.markdown("---")
analyze_button = st.sidebar.button("🚀 Run Analysis", type="primary", width='stretch')

# Main content area
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📋 Instructions")
    st.markdown("""
    1. Upload all required shapefile components (.shp, .shx, .dbf)
    2. Upload DTM file in TIFF format
    3. Set the sampling interval (default: 25m)
    4. Optionally select an attribute field
    5. Click 'Run Analysis' to process
    
    **Slope Classification:**
    - 🟢 **Green**: Acceptable gradient (-1/16 to 1/16)
    - 🔴 **Red**: Steep gradient (outside acceptable range)
    """)

with col2:
    st.subheader("📊 File Status")
    status_data = {
        'File': ['Shapefile (.shp)', 'Index (.shx)', 'Database (.dbf)', 'DTM (.tif)'],
        'Status': [
            '✅ Uploaded' if uploaded_shapefile else '❌ Missing',
            '✅ Uploaded' if uploaded_shx else '❌ Missing',
            '✅ Uploaded' if uploaded_dbf else '❌ Missing',
            '✅ Uploaded' if uploaded_dtm else '❌ Missing'
        ]
    }
    st.dataframe(pd.DataFrame(status_data), hide_index=True, width='stretch')

# Analysis section
if analyze_button:
    if not all([uploaded_shapefile, uploaded_shx, uploaded_dbf, uploaded_dtm]):
        st.error("⚠️ Please upload all required files before running analysis!")
    else:
        try:
            with st.spinner("Processing haul road gradient analysis..."):
                with tempfile.TemporaryDirectory() as tmpdir:
                    # Save shapefile components
                    shp_path = os.path.join(tmpdir, "input.shp")
                    shx_path = os.path.join(tmpdir, "input.shx")
                    dbf_path = os.path.join(tmpdir, "input.dbf")
                    dtm_path = os.path.join(tmpdir, "dtm.tif")
                    
                    with open(shp_path, 'wb') as f:
                        f.write(uploaded_shapefile.read())
                    with open(shx_path, 'wb') as f:
                        f.write(uploaded_shx.read())
                    with open(dbf_path, 'wb') as f:
                        f.write(uploaded_dbf.read())
                    with open(dtm_path, 'wb') as f:
                        f.write(uploaded_dtm.read())
                    
                    if uploaded_prj:
                        prj_path = os.path.join(tmpdir, "input.prj")
                        with open(prj_path, 'wb') as f:
                            f.write(uploaded_prj.read())
                    
                    # Process
                    dxf_buffer, summary_df, detailed_df = process_haul_road(
                        shp_path, dtm_path, segment_length, attribute_field
                    )
            
            st.success("✅ Analysis completed successfully!")
            
            # Display results
            st.markdown("---")
            st.subheader("📈 Summary Results")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    "Total Length",
                    f"{summary_df.iloc[0]['Length (meters)']:.2f} m"
                )
            with col2:
                st.metric(
                    "Green (Acceptable)",
                    f"{summary_df.iloc[1]['Length (meters)']:.2f} m",
                    f"{summary_df.iloc[1]['Percentage']:.1f}%"
                )
            with col3:
                st.metric(
                    "Red (Steep)",
                    f"{summary_df.iloc[2]['Length (meters)']:.2f} m",
                    f"{summary_df.iloc[2]['Percentage']:.1f}%"
                )
            
            st.dataframe(summary_df, width='stretch', hide_index=True)
            
            # Detailed results
            st.markdown("---")
            st.subheader("📋 Detailed Segment Analysis")
            st.dataframe(detailed_df, width='stretch', hide_index=True)
            
            # Download buttons
            st.markdown("---")
            st.subheader("⬇️ Download Results")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.download_button(
                    label="📥 Download DXF",
                    data=dxf_buffer,
                    file_name="haul_road_gradient.dxf",
                    mime="application/dxf"
                )
            
            with col2:
                summary_excel = BytesIO()
                summary_df.to_excel(summary_excel, index=False, sheet_name='Summary')
                summary_excel.seek(0)
                st.download_button(
                    label="📥 Download Summary (Excel)",
                    data=summary_excel,
                    file_name="haul_road_summary.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            
            with col3:
                detailed_excel = BytesIO()
                detailed_df.to_excel(detailed_excel, index=False, sheet_name='Detailed Analysis')
                detailed_excel.seek(0)
                st.download_button(
                    label="📥 Download Detailed (Excel)",
                    data=detailed_excel,
                    file_name="haul_road_detailed.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
        except Exception as e:
            st.error(f"❌ Error during analysis: {str(e)}")
            st.exception(e)

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: gray;'>
    Haul Road Gradient Analysis Tool | Built with Streamlit
    </div>
    """,
    unsafe_allow_html=True
)
