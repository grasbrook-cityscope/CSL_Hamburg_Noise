#!/usr/bin/env python2.7
from __future__ import print_function
import os

from sql_query_builder import get_building_queries, get_road_queries, get_traffic_queries

try:
    import psycopg2
except ImportError:
    print("Did you start the database? Go to /orbisgis_java and Use: 'java -cp '"'bin/*:bundle/*:sys-bundle/*'"' org.h2.tools.Server -pg' in project folder")
    print("Module psycopg2 is missing, cannot connect to PostgreSQL")
    exit(1)


# Returns computation settings
def get_settings():
    return {
        'settings_name': 'max triangle area',
        'max_prop_distance': 750,  # the lower the less accurate
        'max_wall_seeking_distance': 50,  # the lower  the less accurate
        'road_with': 1.5,  # the higher the less accurate
        'receiver_densification': 2.8,  # the higher the less accurate
        'max_triangle_area': 275,  # the higher the less accurate
        'sound_reflection_order': 0,  # the higher the less accurate
        'sound_diffraction_order': 0,  # the higher the less accurate
        'wall_absorption': 0.23,  # the higher the less accurate
    }

# Feeds the geodatabase with the design data and performs the noise computation
# Returns the path of the resulting geojson
def execute_scenario(cursor):
    # Scenario sample
    # Sending/Receiving geometry data using odbc connection is very slow
    # It is advised to use shape file or other storage format, so use SHPREAD or FILETABLE sql functions

    print("make buildings table ..")

    cursor.execute("""
    drop table if exists buildings;
    create table buildings ( the_geom GEOMETRY );
    """)

    buildings_queries = get_building_queries()
    for building in buildings_queries:
        print('building:', building)
        # Inserting building into database
        cursor.execute("""
        -- Insert 1 building from automated string
        INSERT INTO buildings (the_geom) VALUES (ST_GeomFromText({0}));
        """.format(building))

    print("Make roads table (just geometries and road type)..")
    cursor.execute("""
        drop table if exists roads_geom;
        create table roads_geom ( the_geom GEOMETRY, NUM INTEGER, node_from INTEGER, node_to INTEGER, road_type INTEGER);
        """)
    roads_queries = get_road_queries()
    for road in roads_queries:
        print('road:', road)
        cursor.execute("""{0}""".format(road))

    print("Make traffic information table..")
    cursor.execute("""
    drop table if exists roads_traffic;
    create table roads_traffic ( node_from INTEGER, node_to INTEGER, load_speed DOUBLE, junction_speed DOUBLE, max_speed DOUBLE, lightVehicleCount DOUBLE, heavyVehicleCount DOUBLE);
    """)
    traffic_queries = get_traffic_queries()
    for traffic_query in traffic_queries:
        cursor.execute("""{0}""".format(traffic_query))

    print("Duplicate geometries to give sound level for each traffic direction..")

    cursor.execute("""
    drop table if exists roads_dir_one;
    drop table if exists roads_dir_two;
    CREATE TABLE roads_dir_one AS SELECT the_geom,road_type,load_speed,junction_speed,max_speed,lightVehicleCount,heavyVehicleCount FROM roads_geom as geo,roads_traffic traff WHERE geo.node_from=traff.node_from AND geo.node_to=traff.node_to;
    CREATE TABLE roads_dir_two AS SELECT the_geom,road_type,load_speed,junction_speed,max_speed,lightVehicleCount,heavyVehicleCount FROM roads_geom as geo,roads_traffic traff WHERE geo.node_to=traff.node_from AND geo.node_from=traff.node_to;
    -- Collapse two direction in one table
    drop table if exists roads_geo_and_traffic;
    CREATE TABLE roads_geo_and_traffic AS select * from roads_dir_one UNION select * from roads_dir_two;""")

    print("Compute the sound level for each segment of roads..")

    cursor.execute("""
    drop table if exists roads_src_global;
    CREATE TABLE roads_src_global AS SELECT the_geom,BR_EvalSource(load_speed,lightVehicleCount,heavyVehicleCount,junction_speed,max_speed,road_type,ST_Z(ST_GeometryN(ST_ToMultiPoint(the_geom),1)),ST_Z(ST_GeometryN(ST_ToMultiPoint(the_geom),2)),ST_Length(the_geom),False) as db_m from roads_geo_and_traffic;""")

    print("Apply frequency repartition of road noise level..")

    cursor.execute("""
    drop table if exists roads_src;
    CREATE TABLE roads_src AS SELECT the_geom,
    BR_SpectrumRepartition(100,1,db_m) as db_m100,
    BR_SpectrumRepartition(125,1,db_m) as db_m125,
    BR_SpectrumRepartition(160,1,db_m) as db_m160,
    BR_SpectrumRepartition(200,1,db_m) as db_m200,
    BR_SpectrumRepartition(250,1,db_m) as db_m250,
    BR_SpectrumRepartition(315,1,db_m) as db_m315,
    BR_SpectrumRepartition(400,1,db_m) as db_m400,
    BR_SpectrumRepartition(500,1,db_m) as db_m500,
    BR_SpectrumRepartition(630,1,db_m) as db_m630,
    BR_SpectrumRepartition(800,1,db_m) as db_m800,
    BR_SpectrumRepartition(1000,1,db_m) as db_m1000,
    BR_SpectrumRepartition(1250,1,db_m) as db_m1250,
    BR_SpectrumRepartition(1600,1,db_m) as db_m1600,
    BR_SpectrumRepartition(2000,1,db_m) as db_m2000,
    BR_SpectrumRepartition(2500,1,db_m) as db_m2500,
    BR_SpectrumRepartition(3150,1,db_m) as db_m3150,
    BR_SpectrumRepartition(4000,1,db_m) as db_m4000,
    BR_SpectrumRepartition(5000,1,db_m) as db_m5000 from roads_src_global;""")

    print("Please wait, sound propagation from sources through buildings..")

    cursor.execute("""drop table if exists tri_lvl; create table tri_lvl as SELECT * from BR_TriGrid((select 
    st_expand(st_envelope(st_accum(the_geom)), 750, 750) the_geom from ROADS_SRC),'buildings','roads_src','DB_M','',
    {max_prop_distance},{max_wall_seeking_distance},{road_with},{receiver_densification},{max_triangle_area},
    {sound_reflection_order},{sound_diffraction_order},{wall_absorption}); """.format(**get_settings()))

    print("Computation done !")

    print("Create isocountour and save it as a geojson in the working folder..")

    cursor.execute("""
    drop table if exists tricontouring_noise_map;
    -- create table tricontouring_noise_map AS SELECT * from ST_SimplifyPreserveTopology(ST_TriangleContouring('tri_lvl','w_v1','w_v2','w_v3',31622, 100000, 316227, 1000000, 3162277, 1e+7, 31622776, 1e+20));
    create table tricontouring_noise_map AS SELECT * from ST_TriangleContouring('tri_lvl','w_v1','w_v2','w_v3',31622, 100000, 316227, 1000000, 3162277, 1e+7, 31622776, 1e+20);
    -- Merge adjacent triangle into polygons (multiple polygon by row, for unique isoLevel and cellId key)
    drop table if exists multipolygon_iso;
    create table multipolygon_iso as select ST_UNION(ST_ACCUM(the_geom)) the_geom ,idiso, CELL_ID from tricontouring_noise_map GROUP BY IDISO, CELL_ID;
    -- Explode each row to keep only a polygon by row
    drop table if exists simple_noise_map;
    -- example form internet : CREATE TABLE roads2 AS SELECT id_way, ST_PRECISIONREDUCER(ST_SIMPLIFYPRESERVETOPOLOGY(THE_GEOM),0.1),1) the_geom, highway_type t FROM roads; 
    -- ST_SimplifyPreserveTopology(geometry geomA, float tolerance);
    create table simple_noise_map as select ST_SIMPLIFYPRESERVETOPOLOGY(the_geom, 2) the_geom, idiso, CELL_ID from multipolygon_iso;
    drop table if exists contouring_noise_map;
    create table CONTOURING_NOISE_MAP as select the_geom,idiso, CELL_ID from ST_Explode('simple_noise_map'); 
    drop table simple_noise_map; drop table multipolygon_iso;""")

    cwd = os.path.dirname(os.path.abspath(__file__))

    # export result from database to geojson
    # time_stamp = str(datetime.now()).split('.', 1)[0].replace(' ', '_').replace(':', '_')
    name = 'noise_result'
    geojson_path = os.path.abspath(cwd+"/results/" + str(name) + ".geojson")
    cursor.execute("CALL GeoJsonWrite('" + geojson_path + "', 'CONTOURING_NOISE_MAP');")

    return geojson_path


# invokes H2GIS functions in the database
# starts the computation
# returns the path of the resulting file
def compute_noise_propagation():

    # TODO: invoke db from subprocess if not running
    # Define our connection string
    # db name has to be an absolute path
    db_name = (os.path.abspath(".") + os.sep + "mydb").replace(os.sep, "/")
    conn_string = "host='localhost' port=5435 dbname='" + db_name + "' user='sa' password='sa'"

    # print the connection string we will use to connect
    print("Connecting to database\n	->%s" % (conn_string))

    # get a connection, if a connect cannot be made an exception will be raised here
    conn = psycopg2.connect(conn_string)

    # conn.cursor will return a cursor object, you can use this cursor to perform queries
    cursor = conn.cursor()
    print("Connected!\n")

    # Init spatial features
    cursor.execute("CREATE ALIAS IF NOT EXISTS H2GIS_SPATIAL FOR \"org.h2gis.functions.factory.H2GISFunctions.load\";")
    cursor.execute("CALL H2GIS_SPATIAL();")

    # TODO To make faster : not necesscary to initate every time??
    # TODO : call "execute scenario" from grid listener?=
    # Init NoiseModelling functions
    cursor.execute(
        "CREATE ALIAS IF NOT EXISTS BR_PtGrid3D FOR \"org.orbisgis.noisemap.h2.BR_PtGrid3D.noisePropagation\";")
    cursor.execute("CREATE ALIAS IF NOT EXISTS BR_PtGrid FOR \"org.orbisgis.noisemap.h2.BR_PtGrid.noisePropagation\";")
    cursor.execute(
        "CREATE ALIAS IF NOT EXISTS BR_SpectrumRepartition FOR \"org.orbisgis.noisemap.h2.BR_SpectrumRepartition.spectrumRepartition\";")
    cursor.execute(
        "CREATE ALIAS IF NOT EXISTS BR_EvalSource FOR \"org.orbisgis.noisemap.h2.BR_EvalSource.evalSource\";")
    cursor.execute(
        "CREATE ALIAS IF NOT EXISTS BR_SpectrumRepartition FOR \"org.orbisgis.noisemap.h2.BR_SpectrumRepartition.spectrumRepartition\";")
    cursor.execute(
        "CREATE ALIAS IF NOT EXISTS BR_TriGrid FOR \"org.orbisgis.noisemap.h2.BR_TriGrid.noisePropagation\";")
    cursor.execute(
        "CREATE ALIAS IF NOT EXISTS BR_TriGrid3D FOR \"org.orbisgis.noisemap.h2.BR_TriGrid3D.noisePropagation\";")

    # perform calculation
    return execute_scenario(cursor)


def get_result_file_path():
    return compute_noise_propagation()


if __name__ == "__main__":
    get_result_file_path()

    # Try to make noise computation even faster
    # by adjustiong: https://github.com/Ifsttar/NoiseModelling/blob/master/noisemap-core/src/main/java/org/orbisgis/noisemap/core/jdbc/JdbcNoiseMap.java#L30
    # by shifting to GB center
    #   https: // github.com / Ifsttar / NoiseModelling / blob / master / noisemap - core / src / main / java / org / orbisgis / noisemap / core / jdbc / JdbcNoiseMap.java  # L68

