"""
This script contains the Groundwater Flow module of ArcNLET model in the ArcGIS Python Toolbox.

For detailed algorithms, please see https://atmos.eoas.fsu.edu/~mye/ArcNLET/Techican_manual.pdf

@author: Wei Mao <wm23a@fsu.edu>
"""

import datetime
import arcpy
import os
import math
import time
import numpy as np
import pandas as pd
from scipy.stats import hmean
from scipy.ndimage import map_coordinates
from DomenicoRobbins import DomenicoRobbins
# from tps import ThinPlateSpline
import matplotlib.pyplot as plt
import cProfile
import pstats

__version__ = "V1.0.0"


class Transport:
    def __init__(self, c_whethernh4, c_source_location, c_waterbodies, c_particlepath, c_no3output, c_nh4output,
                 c_option0, c_option1, c_option2, c_option3, c_option4, c_option5,
                 c_param1, c_param2, c_param3, c_param4, c_param5, c_param6,
                 c_no3param0, c_no3param1, c_no3param2, c_no3param3, c_no3param4,
                 c_nh4param0, c_nh4param1, c_nh4param2, c_nh4param3, c_nh4param4, c_nh4param5):
        """Initialize the transport module
        """
        if isinstance(c_whethernh4, str):
            self.whether_nh4 = True if c_whethernh4.lower() == 'true' else False
        elif isinstance(c_whethernh4, bool):
            self.whether_nh4 = c_whethernh4
        else:
            arcpy.AddMessage("Error: format of whether to calculate NH4 is wrong.")

        self.source_location = arcpy.Describe(c_source_location).catalogPath if not self.is_file_path(
            c_source_location) else c_source_location
        self.waterbodies = arcpy.Describe(c_waterbodies).catalogPath if not self.is_file_path(
            c_waterbodies) else c_waterbodies
        self.waterbody_raster = None
        self.particle_path = arcpy.Describe(c_particlepath).catalogPath if not self.is_file_path(
            c_particlepath) else c_particlepath
        self.no3_output = os.path.basename(c_no3output) if self.is_file_path(c_no3output) else c_no3output

        self.working_dir = os.path.abspath(os.path.dirname(self.source_location))
        self.no3_output_info = os.path.basename(self.no3_output) + "_info.shp"
        desc = arcpy.Describe(self.source_location)
        self.crs = desc.spatialReference
        field_list = desc.fields

        self.solution_type = c_option0  # solution type, DomenicoRobbinsSS2D or DomenicoRobbinsSSDecay2D
        self.warp_ctrl_pt_spacing = int(c_option1) if isinstance(c_option1, str) else c_option1
        self.warp_method = c_option2.lower()  # Plume warping method, spline, polynomial1, polynomial2
        self.threshold = float(c_option3) if isinstance(c_option3, str) else c_option3  # Threshold concentration
        self.post_process = c_option4.lower()  # Post process, none, medium, and full
        self.solute_mass_type = c_option5  # Solute mass type, specified input mass rate, or specified Z

        self.Y = float(c_param2) if isinstance(c_param2, str) else c_param2  # Y of the source plane
        if self.solute_mass_type.lower() == 'specified z':
            self.Z = float(c_param3) if isinstance(c_param3, str) else c_param3  # Z of the source plane
        else:
            self.mass_in = float(c_param1) if isinstance(c_param1, str) else c_param1  # mass in
            if isinstance(c_param4, str):
                self.zmax_option = True if c_param4.lower() == 'true' else False
            elif isinstance(c_param4, bool):
                self.zmax_option = c_param4
            else:
                arcpy.AddMessage("Error: whether to use Zmax is not specified.")
            if self.zmax_option:
                self.zmax = float(c_param5) if isinstance(c_param5, str) else c_param5  # Max Z of the source plane
        # Plume cell size of the output raster
        self.plume_cell_size = float(c_param6) if isinstance(c_param6, str) else c_param6
        if not any(field.name.lower() == "no3_conc" for field in field_list):
            self.no3_init = float(c_no3param0) if isinstance(c_no3param0, str) else c_no3param0  # NO3 concentration
        else:
            self.no3_init = None
        self.no3_dispx = float(c_no3param1) if isinstance(c_no3param1, str) else c_no3param1  # NO3 dispersion X
        self.no3_dispyz = float(c_no3param2) if isinstance(c_no3param2, str) else c_no3param2  # NO3 dispersion Y and Z
        self.denitrification_rate = float(c_no3param3) if isinstance(c_no3param3, str) else c_no3param3
        self.vol_conversion_factor = float(c_no3param4) if isinstance(c_no3param4, str) else c_no3param4

        self.warp_option = False
        self.multiplier = 1.2

        if self.whether_nh4:
            self.nh4_output = os.path.basename(c_nh4output) if self.is_file_path(c_nh4output) else c_nh4output
            self.nh4_output_info = os.path.basename(self.nh4_output) + "_info.shp"
            if not any(field.name.lower() == "nh4_conc" for field in field_list):
                self.nh4_init = float(c_nh4param0) if isinstance(c_nh4param0, str) else c_nh4param0  # Initial NH4
            else:
                self.nh4_init = None
            self.nh4_dispx = float(c_nh4param1) if isinstance(c_nh4param1, str) else c_nh4param1
            self.nh4_dispyz = float(c_nh4param2) if isinstance(c_nh4param2, str) else c_nh4param2
            self.nitrification_rate = float(c_nh4param3) if isinstance(c_nh4param3, str) else c_nh4param3
            self.bulk_density = float(c_nh4param4) if isinstance(c_nh4param4, str) else c_nh4param4
            self.nh4_adsorption = float(c_nh4param5) if isinstance(c_nh4param5, str) else c_nh4param5

        self.ano3 = 0.0
        self.kno3 = 0.0
        self.no3_Z = 0.0
        self.anh4 = 0.0
        self.knh4 = 0.0
        self.nh4_Z = 0.0

    def calculate_plumes(self):
        current_time = time.strftime("%H:%M:%S", time.localtime())
        arcpy.AddMessage("{}     Calculating plumes...".format(current_time))

        arcpy.env.workspace = self.working_dir
        self.create_new_plume_data_shapefile(self.working_dir)

        # read the segments feature class (flow paths)
        colname = ["Shape", "PathID", "SegID", "TotDist", "TotTime", "SegPrsity", "SegVel", "DirAngle", "WBId",
                   "PathWBId"]
        data = []
        with arcpy.da.SearchCursor(self.particle_path,
                                   ["SHAPE@", "PathID", "SegID", "TotDist", "TotTime", "SegPrsity", "SegVel",
                                    "DirAngle", "WBId", "PathWBId"]) as cursor:
            for row in cursor:
                data.append(row)
        segments = pd.DataFrame(data, columns=colname)
        sorted_segments = segments.sort_values(by=['PathID', 'SegID'])

        current_time = time.strftime("%H:%M:%S", time.localtime())
        arcpy.AddMessage("{}     Creating water body...".format(current_time))
        self.waterbody_raster = r"memory\water_bodies"
        if arcpy.Exists(self.waterbody_raster):
            arcpy.Delete_management(self.waterbody_raster)
        arcpy.conversion.FeatureToRaster(self.waterbodies, "FID", self.waterbody_raster, max(self.plume_cell_size, 1))

        # if not self.no3_output.endswith('.img'):
        #     self.no3_output = self.no3_output + '.img'
        if arcpy.Exists(self.no3_output):
            arcpy.Delete_management(self.no3_output)
        arcpy.management.CreateRasterDataset(self.working_dir, self.no3_output, self.plume_cell_size,
                                             "32_BIT_FLOAT", self.crs, 1)

        if self.whether_nh4:
            # if not self.nh4_output.endswith('.img'):
            #     self.nh4_output = self.nh4_output + '.img'
            if arcpy.Exists(self.nh4_output):
                arcpy.Delete_management(self.nh4_output)
            arcpy.management.CreateRasterDataset(self.working_dir, self.nh4_output, self.plume_cell_size,
                                                 "32_BIT_FLOAT", self.crs, 1)

        no3segments = []
        if self.whether_nh4:
            nh4segments = []
        current_time = time.strftime("%H:%M:%S", time.localtime())
        arcpy.AddMessage("{}     Begin iterating...".format(current_time))

        for pathid in sorted_segments['PathID'].unique():
            seg = sorted_segments[sorted_segments['PathID'] == pathid]
            seg = seg.reset_index(drop=True)
            mean_poro = seg['SegPrsity'].mean()
            mean_velo = hmean(seg['SegVel'])
            mean_angle = seg['DirAngle'].mean()
            max_dist = seg['TotDist'].max()
            maxtime = seg['TotTime'].max()
            wbid = seg['WBId'].iloc[-1]
            path_wbid = seg['PathWBId'].iloc[-1]

            # calculate a single plume
            filtered_no3, filtered_nh4, tmp_list = self.calculate_single_plume(pathid, mean_poro, mean_velo,
                                                                               max_dist)
            current_time = time.strftime("%H:%M:%S", time.localtime())
            arcpy.AddMessage("{}          Calculating reference plume for location: {}".format(current_time, pathid))

            # calculate info file
            current_time = time.strftime("%H:%M:%S", time.localtime())
            arcpy.AddMessage("{}          Calculating info file for location: {}".format(current_time, pathid))
            xvalue, yvalue = tmp_list[0].firstPoint.X, tmp_list[0].firstPoint.Y
            no3seg, nh4seg = self.calculate_info(filtered_no3, filtered_nh4, tmp_list, pathid, mean_poro, mean_velo,
                                                 mean_angle, max_dist, maxtime, wbid, path_wbid)
            no3segments.append(no3seg)

            # warp the plume
            current_time = time.strftime("%H:%M:%S", time.localtime())
            arcpy.AddMessage("{}          Warping plume for location: {}".format(current_time, pathid))
            if self.warp_option:
                warped_no3 = self.warp_affine_transformation(filtered_no3, pathid, xvalue, yvalue, seg)
            else:
                warped_no3, target_body_pts = self.warp_arcgis(filtered_no3, pathid, xvalue, yvalue, seg)
            post_no3 = self.post_process_plume(warped_no3, pathid, seg, target_body_pts)
            arcpy.Mosaic_management(post_no3, self.no3_output, "SUM")
            # max_value = arcpy.GetRasterProperties_management(post_no3, "MAXIMUM")
            # print('The maximum value of the plume is: {}'.format(max_value))
            # arcpy.CalculateStatistics_management(self.no3_output)
            # max_value = arcpy.GetRasterProperties_management(self.no3_output, "MAXIMUM")
            # print('The maximum value of all the plume is: {}'.format(max_value))

            if self.whether_nh4:
                nh4segments.append(nh4seg)
                if self.warp_option:
                    warped_nh4 = self.warp_affine_transformation(filtered_nh4, pathid, xvalue, yvalue, seg)
                else:
                    warped_nh4, target_body_pts = self.warp_arcgis(filtered_nh4, pathid, xvalue, yvalue, seg)
                post_nh4 = self.post_process_plume(warped_nh4, pathid, seg, target_body_pts)
                arcpy.Mosaic_management(post_nh4, self.nh4_output, "SUM")

        arcpy.Delete_management(post_no3)
        if self.whether_nh4:
            arcpy.Delete_management(post_nh4)

        out_raster = arcpy.sa.SetNull(self.no3_output, self.no3_output, "VALUE < {}".format(self.threshold))
        if arcpy.Exists(self.no3_output):
            arcpy.Delete_management(self.no3_output)
        out_raster.save(self.no3_output)
        if self.post_process == "medium":
            if not self.whether_nh4:
                self.nh4_output = None
            self.post_process_medium(self.no3_output, self.nh4_output)
        arcpy.CalculateStatistics_management(self.no3_output)
        if self.whether_nh4:
            arcpy.CalculateStatistics_management(self.nh4_output)

        with arcpy.da.InsertCursor(self.no3_output_info, ["SHAPE@", "PathID", "is2D", "domBdy", "decayCoeff",
                                                          "avgVel", "avgPrsity", "DispL", "DispTH", "DispTV",
                                                          "SourceY", "SourceZ", "MeshDX", "MeshDY", "MeshDZ",
                                                          "plumeTime", "pathTime", "plumeLen", "pathLen", "plumeArea",
                                                          "mslnRtNmr", "massInRate", "massDNRate", "srcAngle", "warp",
                                                          "PostP", "Init_conc", "VolFac", "nextConc", "threshConc",
                                                          "WBId_plume", "WBId_path"]) as cursor:
            for row in no3segments:
                cursor.insertRow(row)
        if self.whether_nh4:
            with arcpy.da.InsertCursor(self.nh4_output_info, ["SHAPE@", "PathID", "is2D", "domBdy", "decayCoeff",
                                                              "avgVel", "avgPrsity", "DispL", "DispTH", "DispTV",
                                                              "SourceY", "SourceZ", "MeshDX", "MeshDY", "MeshDZ",
                                                              "plumeTime", "pathTime", "plumeLen", "pathLen",
                                                              "plumeArea", "mslnRtNmr", "massInRate", "massDNRate",
                                                              "srcAngle", "warp", "PostP", "Init_conc", "VolFac",
                                                              "nextConc", "threshConc", "WBId_plume", "WBId_path"]
                                       ) as cursor:
                for row in nh4segments:
                    cursor.insertRow(row)
        return

    def calculate_single_plume(self, pathid, mean_poro, mean_velo, max_dist):
        """
        Calculate a single plume
        """
        current_time = time.strftime("%H:%M:%S", time.localtime())
        arcpy.AddMessage("{}     Calculating plume for location: {}".format(current_time, pathid))
        try:
            point, no3_conc, nh4_conc = self.get_initial_conc(pathid)
            ny = int(self.Y / self.plume_cell_size)
            nx = math.ceil(max_dist / self.plume_cell_size)
            nx_old = nx
            if self.post_process != 'none':
                nx = nx + int(ny * self.multiplier)

            if self.whether_nh4:
                self.kno3 = self.denitrification_rate
                self.knh4 = self.nitrification_rate * (1 + self.nh4_adsorption * self.bulk_density / mean_poro)
                self.ano3 = no3_conc + self.knh4 / (self.knh4 - self.kno3) * nh4_conc
                self.anh4 = nh4_conc
                if self.solute_mass_type.lower() == 'specified input mass rate':
                    a2 = self.no3_init + self.nh4_init * self.knh4 / (self.knh4 - self.kno3)
                    dispcons = -(self.kno3 / (self.kno3 - self.knh4)) * self.anh4 * (
                            0.5 + 0.5 * math.sqrt(1 + 4 * self.knh4 * self.no3_dispx / mean_velo))
                    dispcons1 = a2 * (0.5 + 0.5 * math.sqrt(1 + 4 * self.kno3 * self.no3_dispx / mean_velo))
                    self.no3_Z = self.mass_in / (self.Y * mean_poro * mean_velo * self.vol_conversion_factor *
                                                 max(dispcons1, dispcons + dispcons1))
                    dispcons = -(self.kno3 / (self.kno3 - self.knh4)) * self.anh4 * (
                            0.5 + 0.5 * math.sqrt(1 + 4 * self.knh4 * self.nh4_dispx / mean_velo))
                    dispcons1 = a2 * (0.5 + 0.5 * math.sqrt(1 + 4 * self.kno3 * self.nh4_dispx / mean_velo))
                    self.nh4_Z = self.mass_in / (self.Y * mean_poro * mean_velo * self.vol_conversion_factor *
                                                 max(dispcons1, dispcons + dispcons1))
                    if self.nh4_Z < 0:
                        self.nh4_Z = min(0.0001, self.zmax) if self.zmax_option else 0.0001
                    if self.solute_mass_type.lower() == 'specified input mass rate':
                        if self.zmax_option:
                            if self.nh4_Z > self.zmax:
                                self.nh4_Z = self.zmax
                else:
                    self.no3_Z = self.Z
                    self.nh4_Z = self.Z
            else:
                self.kno3 = self.denitrification_rate
                self.ano3 = no3_conc
                if self.solute_mass_type.lower() == 'specified input mass rate':
                    self.no3_Z = self.mass_in * 2 / (
                            self.Y * mean_poro * mean_velo * self.ano3 * self.vol_conversion_factor * (
                            1 + math.sqrt(1 + 4 * self.kno3 * self.no3_dispx / mean_velo)))
                else:
                    self.no3_Z = self.Z
            if self.no3_Z < 0:
                self.no3_Z = min(0.0001, self.zmax) if self.zmax_option else 0.0001
            if self.solute_mass_type.lower() == 'specified input mass rate':
                if self.zmax_option:
                    if self.no3_Z > self.zmax:
                        self.no3_Z = self.zmax

            if self.whether_nh4:
                "calculate both no3 and nh4"
                '''Note, the original code use self.average_theta, which based on inputs and is a constant value for
                   each plume. But in this code, we use the average porosity calculated based on the particle path file.
                '''
                dr4 = DomenicoRobbins(self.solution_type, self.anh4, self.nh4_dispx, self.nh4_dispyz, self.nh4_dispyz,
                                      self.Y, self.nh4_Z, self.knh4, mean_velo, -1)

                dr3 = DomenicoRobbins(self.solution_type, self.ano3, self.no3_dispx, self.no3_dispyz, self.no3_dispyz,
                                      self.Y, self.no3_Z, self.kno3, mean_velo, -1)

                edge = 500
                while True:
                    xlist = np.arange(1, nx + 1) * self.plume_cell_size  # - self.plume_cell_size / 2
                    if ny % 2 != 0:
                        ylist = np.arange(-edge, edge + 1) * self.plume_cell_size
                    else:
                        ylist = np.arange(-edge, edge) * self.plume_cell_size  # + self.plume_cell_size / 2

                    nh4result = dr4.eval(xlist, ylist, 0)
                    no3result = dr3.eval(xlist, ylist, 0)

                    no3result = no3result - self.knh4 / (self.knh4 - self.kno3) * nh4result

                    if (no3result[0, :].all() <= self.threshold and no3result[-1, :].all() <= self.threshold) and \
                            (nh4result[0, :].all() <= self.threshold and nh4result[-1, :].all() <= self.threshold):

                        no3y = np.zeros((len(ylist)))
                        nh4y = np.zeros((len(ylist)))
                        if ny % 2 != 0:
                            no3y[math.floor(len(ylist) / 2) - math.floor(ny / 2):
                                 math.floor(len(ylist) / 2) - math.floor(ny / 2) + ny] = no3_conc
                            nh4y[math.floor(len(ylist) / 2) - math.floor(ny / 2):
                                 math.floor(len(ylist) / 2) - math.floor(ny / 2) + ny] = nh4_conc
                        else:
                            no3y[len(ylist) / 2 - ny / 2: len(ylist) / 2 + ny / 2] = no3_conc
                            nh4y[len(ylist) / 2 - ny / 2: len(ylist) / 2 + ny / 2] = nh4_conc
                        no3result = np.hstack((no3y.reshape(-1, 1), no3result))
                        nh4result = np.hstack((nh4y.reshape(-1, 1), nh4result))

                        row_to_delete = np.all(no3result <= self.threshold, axis=1)
                        filtered_no3result = no3result[~row_to_delete]
                        cols_to_delete = np.all(filtered_no3result <= self.threshold, axis=0)
                        filtered_no3result = filtered_no3result[:, ~cols_to_delete]

                        row_to_delete = np.all(nh4result <= self.threshold, axis=1)
                        filtered_nh4result = nh4result[~row_to_delete]
                        cols_to_delete = np.all(filtered_nh4result <= self.threshold, axis=0)
                        filtered_nh4result = filtered_nh4result[:, ~cols_to_delete]
                        break
                    else:
                        edge = edge + 100

                # np.savetxt("nh4results.txt", filtered_nh4result)
                # np.savetxt("no3results.txt", filtered_no3result)
                no3_plume_len = nx_old
                nh4_plume_len = nx_old
                if self.post_process != 'none':
                    if filtered_no3result.shape[1] < nx_old:
                        no3_plume_len = filtered_no3result.shape[1]
                    if filtered_nh4result.shape[1] < nx_old:
                        nh4_plume_len = filtered_nh4result.shape[1]
                output_list = [point, no3_plume_len, nh4_plume_len]

                return filtered_no3result, filtered_nh4result, output_list
            else:
                "only calculate no3"
                dr = DomenicoRobbins(self.solution_type, self.ano3, self.no3_dispx, self.no3_dispyz, self.no3_dispyz,
                                     self.Y, self.no3_Z, self.kno3, mean_velo, -1)
                edge = 500
                while True:
                    xlist = np.arange(1, nx + 1) * self.plume_cell_size
                    if ny % 2 != 0:
                        ylist = np.arange(-edge, edge + 1) * self.plume_cell_size
                    else:
                        ylist = np.arange(-edge, edge) * self.plume_cell_size + self.plume_cell_size / 2

                    no3result = dr.eval(xlist, ylist, 0)
                    if no3result[0, :].all() <= self.threshold and no3result[-1, :].all() <= self.threshold:

                        no3y = np.zeros((len(ylist)))
                        if ny % 2 != 0:
                            no3y[math.floor(len(ylist) / 2) - math.floor(ny / 2):
                                 math.floor(len(ylist) / 2) - math.floor(ny / 2) + ny] = no3_conc
                        else:
                            no3y[len(ylist) / 2 - ny / 2: len(ylist) / 2 + ny / 2] = no3_conc
                        no3result = np.hstack((no3y.reshape(-1, 1), no3result))

                        row_to_delete = np.all(no3result <= self.threshold, axis=1)
                        filtered_no3result = no3result[~row_to_delete]
                        cols_to_delete = np.all(filtered_no3result <= self.threshold, axis=0)
                        filtered_no3result = filtered_no3result[:, ~cols_to_delete]
                        break
                    else:
                        edge = edge + 100

                # np.savetxt("no3results.txt", no3result)
                no3_plume_len = nx_old
                if self.post_process != 'none':
                    if filtered_no3result.shape[1] < nx_old:
                        no3_plume_len = filtered_no3result.shape[1]
                output_list = [point, no3_plume_len, 0]
                return filtered_no3result, None, output_list

        except Exception as e:
            arcpy.AddMessage("[Error] Calculate single plume {}: ".format(pathid) + str(e))
            return False

    def calculate_info(self, filtered_no3result, filtered_nh4result, tmp_list, pathid, mean_poro, mean_velo, mean_angle,
                       max_dist, maxtime, wbid, path_wbid):
        """
        Calculate the info file
        """
        point = tmp_list[0]
        no3plumelen = tmp_list[1] * self.plume_cell_size
        no3_results = filtered_no3result[:, 0: tmp_list[1]]
        if self.whether_nh4:
            nh4plumelen = tmp_list[2] * self.plume_cell_size
            nh4_results = filtered_nh4result[:, 0: tmp_list[2]]

        no3plumearea = (no3_results > self.threshold).sum() * self.plume_cell_size ** 2
        non_zero_indices = np.nonzero(no3_results[:, 0])
        no3massinratemt3d = (mean_poro * self.plume_cell_size * self.no3_Z * mean_velo * self.vol_conversion_factor *
                             (self.no3_init - self.no3_dispx * (
                                     no3_results[non_zero_indices, 1] - self.no3_init) / self.plume_cell_size)).sum()
        if self.whether_nh4:
            nh4plumearea = (nh4_results > self.threshold).sum() * self.plume_cell_size ** 2
            non_zero_indices = np.nonzero(nh4_results[:, 0])
            nh4massinratemt3d = (mean_poro * self.plume_cell_size * self.nh4_Z * mean_velo *
                                 self.vol_conversion_factor * (self.nh4_init - self.nh4_dispx * (
                            nh4_results[non_zero_indices, 1] - self.nh4_init) / self.plume_cell_size)).sum()

        if self.solute_mass_type.lower() == 'specified input mass rate':
            dombdy = 1
            if self.whether_nh4:
                no3massin = self.mass_in * self.no3_init / (self.no3_init + self.nh4_init)
                nh4massin = self.mass_in * self.nh4_init / (self.no3_init + self.nh4_init)
            else:
                no3massin = self.mass_in
        elif self.solute_mass_type.lower() == 'specified z':
            dombdy = 2
            if self.whether_nh4:
                nh4massin = mean_velo * mean_poro * self.nh4_Z * self.Y * self.vol_conversion_factor * self.nh4_init * (
                        0.5 + 0.5 * math.sqrt(1 + (4 * self.knh4 * self.nh4_dispx) / mean_velo))

                dispcon0 = 0.5 * self.nh4_init * (self.knh4 / (self.knh4 - self.kno3)) * (
                        math.sqrt(1 + 4 * self.kno3 * self.no3_dispx / mean_velo) - math.sqrt(
                    1 + (4 * self.knh4 * self.no3_dispx) / mean_velo))
                dispcon1 = self.no3_init * (0.5 + 0.5 * math.sqrt(1 + (4 * self.kno3 * self.no3_dispx) / mean_velo))
                no3massin = mean_velo * mean_poro * self.no3_Z * self.Y * self.vol_conversion_factor * max(
                    dispcon1, dispcon1 + dispcon0)
            else:
                no3massin = mean_velo * mean_poro * self.no3_Z * self.Y * self.vol_conversion_factor * self.no3_init * (
                        0.5 + 0.5 * math.sqrt(1 + (4 * self.kno3 * self.no3_dispx) / mean_velo))

        no3mdn = (self.kno3 * mean_poro * self.no3_Z * self.plume_cell_size * self.plume_cell_size *
                  self.vol_conversion_factor * no3_results[:, 1:]).sum()
        no3nextconc = no3_results[:, 1].max()
        if self.whether_nh4:
            nh4mdn = (self.knh4 * mean_poro * self.nh4_Z * self.plume_cell_size * self.plume_cell_size *
                      self.vol_conversion_factor * nh4_results).sum()
            nh4nextconc = max(no3_results[:, 1].max(), nh4_results[:, 1].max())

        if self.post_process == "none":
            processes = 0
        elif self.post_process == "medium":
            processes = 1
        elif self.post_process == "full":
            processes = 2

        if self.warp_method == "spline":
            warp_method = 0
        elif self.warp_method == "polyorder1":
            warp_method = 1
        elif self.warp_method == "polyorder2":
            warp_method = 2

        if no3plumelen < max_dist:
            no3wbid = -1
        else:
            no3wbid = wbid

        no3segment = [point, pathid, 1, dombdy, self.kno3, mean_velo, mean_poro, self.no3_dispx,
                      self.no3_dispyz, 0, self.Y, self.no3_Z, self.plume_cell_size, self.plume_cell_size, self.no3_Z,
                      -1, maxtime, no3plumelen, max_dist, no3plumearea, no3massinratemt3d, no3massin, no3mdn,
                      mean_angle, warp_method, processes, self.no3_init, self.vol_conversion_factor, no3nextconc,
                      self.threshold, no3wbid, path_wbid]
        nh4segment = []
        if self.whether_nh4:
            if nh4plumelen < max_dist:
                nh4wbid = -1
            else:
                nh4wbid = wbid

            nh4segment = [point, pathid, 1, dombdy, self.knh4, mean_velo, mean_poro, self.nh4_dispx,
                          self.nh4_dispyz, 0, self.Y, self.nh4_Z, self.plume_cell_size, self.plume_cell_size,
                          self.nh4_Z, -1, maxtime, nh4plumelen, max_dist, nh4plumearea, nh4massinratemt3d, nh4massin,
                          nh4mdn, mean_angle, warp_method, processes, self.nh4_init, self.vol_conversion_factor,
                          nh4nextconc, self.threshold, nh4wbid, path_wbid]

        return no3segment, nh4segment

    def warp_affine_transformation(self, plume_array, pathid, xvalue, yvalue, segment):
        """
        Warp the plume
        """
        row, col = plume_array.shape
        nshape = row + col
        max_value = plume_array.max()

        if row % 2 == 0:
            input_array = np.zeros((2 * nshape, 2 * nshape))
            input_array[nshape - int(row / 2): nshape + int(row / 2), nshape: nshape + col] = plume_array
        else:
            input_array = np.zeros((2 * nshape + 1, 2 * nshape))
            input_array[nshape - int(row / 2): nshape + int(row / 2) + 1, nshape: nshape + col] = plume_array

        center_pts, body_pts = self.get_control_points(plume_array)
        target_center_pts, target_body_pts = self.get_target_points(segment, center_pts, body_pts)

        source_pts = np.vstack((center_pts, body_pts[:, [0, 1]], body_pts[:, [0, 2]]))
        deform_pts = np.vstack((target_center_pts, target_body_pts))

        # col_max = math.ceil(max(source_pts[:, 0].max(), deform_pts[:, 0].max()))
        # col_min = math.ceil(min(source_pts[:, 0].min(), deform_pts[:, 0].min()))
        # row_max = math.ceil(max(source_pts[:, 1].max(), deform_pts[:, 1].max()))
        # row_min = math.ceil(min(source_pts[:, 1].min(), deform_pts[:, 1].min()))
        # input_array = input_array[row_min - 1: row_max + 2, col_min - 1:col_max + 2]
        # source_pts = source_pts - np.array([col_min, row_min]) + 1
        # deform_pts = deform_pts - np.array([col_min, row_min]) + 1

        # tps = ThinPlateSpline(0.5)
        # tps.fit(source_pts, deform_pts)
        #
        # height, width = input_array.shape
        # output_indices = np.indices((height, width), dtype=np.int16).transpose(1, 2, 0)  # Shape: (H, W, 2)
        # input_indices = tps.transform(output_indices.reshape(-1, 2)).reshape(height, width, 2)
        # warped_array = map_coordinates(input_array, input_indices.transpose(2, 0, 1))

        # target_body_pts[:, 0] = target_body_pts[:, 0] - col_min
        # target_body_pts[:, 1: 2] = target_body_pts[:, 1: 2] - row_min
        # modified_warped_array = self.modify_warped_array(warped_array, target_body_pts, plume_array, max_value)
        #
        # if row % 2 == 0:
        #     new_xvalue = xvalue - self.plume_cell_size * (nshape + 1 / 2)
        #     new_yvalue = yvalue - self.plume_cell_size * (nshape + 1 / 2)
        # else:
        #     new_xvalue = xvalue - self.plume_cell_size * (nshape + 1 / 2)
        #     new_yvalue = yvalue - self.plume_cell_size * (nshape + 1 / 2)

        # plt.figure(figsize=(10, 5))
        # plt.subplot(1, 2, 1)
        # input_array[input_array < self.threshold] = np.nan
        # plt.imshow(input_array)
        # plt.scatter(source_pts[:, 0], source_pts[:, 1], c='r')
        # plt.subplot(1, 2, 2)
        # plt.imshow(modified_warped_array)
        # plt.scatter(deform_pts[:, 0] + 1 / 2, deform_pts[:, 1] + 1 / 2, c='r')
        # plt.gca().invert_yaxis()
        # figname = name + '_{}'.format(pathid)
        # plt.savefig(figname+'.png')
        # # plt.show()

        name = r'memory\plume_raster'
        if arcpy.Exists(name):
            arcpy.Delete_management(name)
        # warped_raster = arcpy.NumPyArrayToRaster(modified_warped_array[::-1], arcpy.Point(new_xvalue, new_yvalue),
        #                                          self.plume_cell_size, self.plume_cell_size)
        # arcpy.management.DefineProjection(warped_raster, self.crs)
        # warped_raster.save(name)

        return name

    def warp_arcgis(self, plume_array, pathid, xvalue, yvalue, segment):
        """
        Warp the plume
        """
        try:
            center_pts, body_pts = self.get_control_points(plume_array, True)
            y_lower_left = yvalue - plume_array.shape[0] * self.plume_cell_size / 2
            plume_array[plume_array <= self.threshold] = np.nan
            if arcpy.Exists(r'memory\plume_raster'):
                arcpy.Delete_management(r'memory\plume_raster')
            plume_raster = arcpy.NumPyArrayToRaster(plume_array, arcpy.Point(xvalue, y_lower_left),
                                                    self.plume_cell_size, self.plume_cell_size)
            arcpy.management.DefineProjection(plume_raster, self.crs)
            # plume_raster.save('plume_raster')

            results = self.get_target_points_gis(segment, center_pts, body_pts, xvalue, yvalue)
            target_center_pts, origin_center_pts, target_body_pts, origin_body_pts = results
            source_control_points = np.vstack((origin_center_pts, origin_body_pts))
            target_control_points = np.vstack((target_center_pts, target_body_pts))
            source_control_points = ';'.join([f"'{x} {y}'" for x, y in source_control_points])
            target_control_points = ';'.join([f"'{x} {y}'" for x, y in target_control_points])

            name = r'memory\plume_raster'
            if arcpy.Exists(name):
                arcpy.Delete_management(name)
            arcpy.management.Warp(plume_raster, source_control_points, target_control_points, name,
                                  self.warp_method.upper(), "BILINEAR")

            # control_point = np.vstack((target_center_pts, target_body_pts))
            # array = []
            # for i in range(control_point.shape[0]):
            #     array.append((i + 1, (control_point[i, 0], control_point[i, 1])))
            # array = np.array(array, np.dtype([("idfield", np.int32), ("XY", "<f8", 2)]))
            # pname = os.path.join(arcpy.env.workspace, name+'point_{}'.format(pathid))
            # if arcpy.Exists(pname):
            #     arcpy.Delete_management(pname)
            # arcpy.da.NumPyArrayToFeatureClass(array, pname, ['XY'], self.crs)

            return name, target_body_pts
        except Exception as e:
            arcpy.AddMessage("Plume {} cannot be warped.".format(pathid))
            arcpy.AddMessage("[Error] Get_control_points: " + str(e))
            return None

    def post_process_plume(self, name, pathid, segment, target_body_pts):
        """
        Post process the plume
        """
        fname = r'memory\Resample'
        if arcpy.Exists(fname):
            arcpy.Delete_management(fname)
        if pathid != 0:
            arcpy.env.snapRaster = self.no3_output
            arcpy.Resample_management(name, fname, str(self.plume_cell_size), "NEAREST")
        else:
            fname = name
        # arcpy.CopyRaster_management(fname, 'Resample.tif')

        if self.post_process == 'none' or self.post_process == 'medium':
            if pathid != 0:
                return fname
            else:
                return name
        elif self.post_process == 'full':
            if segment["WBId"].iloc[-1] != -1:
                point_list = []
                for row in target_body_pts:
                    point = arcpy.Point(row[0], row[1])
                    point_list.append(point)
                polyline = arcpy.Polyline(arcpy.Array(point_list), self.crs)
                if arcpy.Exists(r'memory\polyline'):
                    arcpy.Delete_management(r'memory\polyline')
                arcpy.CopyFeatures_management(polyline, r'memory\polyline')

                inFeatures = [r'memory\polyline', self.waterbodies]
                outFeatures = r'memory\polygon'
                if arcpy.Exists(outFeatures):
                    arcpy.Delete_management(outFeatures)
                arcpy.FeatureToPolygon_management(inFeatures, outFeatures, "", "NO_ATTRIBUTES")
                Erase_polygon = r'memory\Erase_polygon'
                if arcpy.Exists(Erase_polygon):
                    arcpy.Delete_management(Erase_polygon)
                arcpy.Erase_analysis(outFeatures, self.waterbodies, Erase_polygon)

                save_name = name.split('.')[0] + '_full' + '.tif'
                if arcpy.Exists(save_name):
                    arcpy.Delete_management(save_name)
                try:
                    arcpy.sa.ExtractByMask(fname, Erase_polygon).save(save_name)

                    return save_name
                except arcpy.ExecuteError as e:

                    while True:
                        with arcpy.da.UpdateCursor(r'memory\polyline', ['SHAPE@']) as cursor:
                            for row in cursor:
                                polyline = row[0]

                                first_point = polyline.firstPoint
                                last_point = polyline.lastPoint
                                new_first_x = 2 * first_point.X - polyline.getPart(0)[1].X
                                new_first_y = 2 * first_point.Y - polyline.getPart(0)[1].Y
                                new_last_x = 2 * last_point.X - polyline.getPart(0)[-2].X
                                new_last_y = 2 * last_point.Y - polyline.getPart(0)[-2].Y

                                # new_point1 = arcpy.Point(new_first_x, new_first_y)
                                # new_point2 = arcpy.Point(new_last_x, new_last_y)

                                new_part = arcpy.Array()
                                new_part.add(arcpy.Point(new_first_x, new_first_y))
                                for point in polyline.getPart(0):
                                    new_part.add(point)
                                new_part.add(arcpy.Point(new_last_x, new_last_y))

                                new_polyline = arcpy.Polyline(new_part)
                                row[0] = new_polyline
                                cursor.updateRow(row)

                        if arcpy.Exists(r'memory\Intersect'):
                            arcpy.Delete_management(r'memory\Intersect')
                        arcpy.analysis.Intersect([r'memory\polyline', self.waterbodies], r'memory\Intersect')
                        ppp = arcpy.da.SearchCursor(r'memory\Intersect', ["SHAPE@"]).next()[0]
                        if ppp.isMultipart:
                            break

                    inFeatures = [r'memory\polyline', self.waterbodies]
                    outFeatures = r'memory\polygon'
                    if arcpy.Exists(outFeatures):
                        arcpy.Delete_management(outFeatures)
                    arcpy.FeatureToPolygon_management(inFeatures, outFeatures, "", "NO_ATTRIBUTES")
                    Erase_polygon = r'memory\Erase_polygon'
                    if arcpy.Exists(Erase_polygon):
                        arcpy.Delete_management(Erase_polygon)
                    arcpy.Erase_analysis(outFeatures, self.waterbodies, Erase_polygon)

                    save_name = name.split('.')[0] + '_full' + '.tif'
                    if arcpy.Exists(save_name):
                        arcpy.Delete_management(save_name)
                    arcpy.sa.ExtractByMask(fname, Erase_polygon).save(save_name)

                    return save_name
            else:
                return fname

    def post_process_medium(self, no3_output, nh4_output=None):
        """
        Medium post process the plume
        """
        no3 = arcpy.sa.ExtractByMask(no3_output, self.waterbodies, "OUTSIDE")
        if arcpy.Exists(self.no3_output):
            arcpy.Delete_management(self.no3_output)
        no3.save(self.no3_output)

        if self.whether_nh4:
            if nh4_output is None:
                arcpy.AddMessage("The nh4_output is None!")
            nh4 = arcpy.sa.ExtractByMask(nh4_output, self.waterbodies, "OUTSIDE")
            if arcpy.Exists(self.nh4_output):
                arcpy.Delete_management(self.nh4_output)
            nh4 = arcpy.sa.SetNull(nh4, nh4, "VALUE < {}".format(self.threshold))
            nh4.save(self.nh4_output)
        return

    def get_initial_conc(self, fid):
        """
        Get the initial concentration of the no3 and nh4
        """
        try:
            desc = arcpy.Describe(self.source_location)
            field_list = desc.fields
            no3_exists = any(field.name.lower() == "no3_conc" for field in field_list)
            nh4_exists = any(field.name.lower() == "nh4_conc" for field in field_list)

            query = "FID = {}".format(fid)
            if self.whether_nh4:
                if no3_exists and nh4_exists:
                    cursor = arcpy.da.SearchCursor(self.source_location, ["SHAPE@", "FID", "no3_conc", "nh4_conc"],
                                                   query)
                    row = cursor.next()
                    point = row[0]
                    no3_conc = row[2]
                    nh4_conc = row[3]
                    self.no3_init = no3_conc
                    self.nh4_init = nh4_conc
                elif (not no3_exists) and nh4_exists:
                    cursor = arcpy.da.SearchCursor(self.source_location, ["SHAPE@", "FID", "nh4_conc"], query)
                    row = cursor.next()
                    point = row[0]
                    no3_conc = self.no3_init
                    nh4_conc = row[2]
                    self.nh4_init = nh4_conc
                elif no3_exists and (not nh4_exists):
                    cursor = arcpy.da.SearchCursor(self.source_location, ["SHAPE@", "FID", "no3_conc"], query)
                    row = cursor.next()
                    point = row[0]
                    no3_conc = row[2]
                    self.no3_init = no3_conc
                    nh4_conc = self.nh4_init
                else:
                    cursor = arcpy.da.SearchCursor(self.source_location, ["SHAPE@", "FID"], query)
                    row = cursor.next()
                    point = row[0]
                    no3_conc = self.no3_init
                    nh4_conc = self.nh4_init
            else:
                if no3_exists:
                    cursor = arcpy.da.SearchCursor(self.source_location, ["SHAPE@", "FID", "no3_conc"], query)
                    row = cursor.next()
                    point = row[0]
                    no3_conc = row[2]
                    nh4_conc = 0
                    self.no3_init = no3_conc
                else:
                    cursor = arcpy.da.SearchCursor(self.source_location, ["SHAPE@", "FID"], query)
                    row = cursor.next()
                    point = row[0]
                    no3_conc = self.no3_init
                    nh4_conc = 0
            return point, no3_conc, nh4_conc
        except Exception as e:
            arcpy.AddMessage("[Error] Can not get initial value of NO3 and NH4: " + str(e))
            return None, None, None

    def create_new_plume_data_shapefile(self, save_path):
        """Create a new shapefile to store the plume data
        """
        try:
            # Create a list to hold field information
            if arcpy.Exists(self.no3_output_info):
                arcpy.Delete_management(self.no3_output_info)

            create_shapefile(save_path, self.no3_output_info, self.crs)

            if self.whether_nh4:
                if arcpy.Exists(self.nh4_output_info):
                    arcpy.Delete_management(self.nh4_output_info)
                create_shapefile(save_path, self.nh4_output_info, self.crs)

        except Exception as e:
            print(self.no3_output_info)
            arcpy.AddMessage("[Error] Create_new_plume_data_shapefile: " + str(e))
            return None

    def get_control_points(self, plume_array, ifgis=False):
        """
        Get the control points for warping
        """
        plumelen = plume_array.shape[1]
        if plumelen < 3:
            raise ValueError("The length of the plume is too short!")

        # get the number of center line control points
        warp_ctrl_pt_spacing = self.warp_ctrl_pt_spacing
        center_number = math.ceil(plumelen / warp_ctrl_pt_spacing) + 1
        while center_number < 10:
            warp_ctrl_pt_spacing = warp_ctrl_pt_spacing / 2
            center_number = math.ceil(plumelen / warp_ctrl_pt_spacing) + 1
            if warp_ctrl_pt_spacing <= 1:
                raise ValueError("The number of center line control points is too small!")

        # get the center line control points
        index_array = np.arange(0, plumelen)
        center_pts = index_array[::int(warp_ctrl_pt_spacing)]
        if (plumelen - 1) % warp_ctrl_pt_spacing != 0:
            center_pts = np.append(center_pts, plumelen - 1)
        values_to_add = np.array([1, 2, 3, 4, 5])
        center_pts = np.sort(np.append(center_pts, values_to_add))

        # get the start and end points bigger than the threshold
        if plume_array[:, -1].max() >= self.threshold:
            cols = plume_array[:, center_pts]
        else:
            cols = plume_array[:, center_pts[:-1]]
        starts = []
        for col in cols.T:
            start = np.where(col > self.threshold)[0][0]
            starts.append(start)
        ends = [len(col) - 1 - start for start in starts]

        starts = np.array(starts)
        ends = np.array(ends)
        body_pts = np.vstack((starts, ends)).T

        if ifgis:
            return center_pts, body_pts

        # get the x, y index of the center line control points in the big temp array
        nrow, ncol = plume_array.shape
        nshape = nrow + ncol
        # set lower left corner as the origin
        x_value = center_pts + nshape
        y_value = np.full_like(x_value, nshape)
        center_pts_new = np.vstack((x_value, y_value)).T

        # get the x, y index of the body control points in the big temp array
        if plume_array[:, -1].max() >= self.threshold:
            body_pts = np.hstack(((center_pts + nshape).reshape(-1, 1), body_pts))
        else:
            body_pts = np.hstack(((center_pts[:-1] + nshape).reshape(-1, 1), body_pts))
        if nrow % 2 == 0:
            body_pts[:, 1] = nshape + int(nrow / 2) - body_pts[:, 1] - 1
            body_pts[:, 2] = nshape + int(nrow / 2) - body_pts[:, 2] - 1
        else:
            body_pts[:, 1] = nshape + int(nrow / 2) - body_pts[:, 1]
            body_pts[:, 2] = nshape + int(nrow / 2) - body_pts[:, 2]
        # np.savetxt("plume_array.txt", plume_array, delimiter=',')
        body_pts_new = body_pts

        return center_pts_new, body_pts_new

    def get_target_points(self, segment, center_pts, body_pts):
        """
        Get the target points for warping
        """
        target_center_pts = []
        target_body_right_pts = []
        target_body_left_pts = []

        segment['dist'] = segment['TotDist'] - segment['TotDist'].shift(1)
        segment.loc[0, 'dist'] = segment['TotDist'].iloc[0]

        x_origin_value = segment['Shape'].iloc[0].firstPoint.X
        y_origin_value = segment['Shape'].iloc[0].firstPoint.Y
        for i in range(len(center_pts)):
            length = (center_pts[i, 0] - center_pts[0, 0]) * self.plume_cell_size
            index = (segment['TotDist'] >= length).idxmax()
            if i == len(center_pts) - 1 and index == 0:
                index = len(segment) - 1
            first_x = segment['Shape'].iloc[index].firstPoint.X
            first_y = segment['Shape'].iloc[index].firstPoint.Y
            last_x = segment['Shape'].iloc[index].lastPoint.X
            last_y = segment['Shape'].iloc[index].lastPoint.Y
            target_x = last_x - (last_x - first_x) / segment['dist'].iloc[index] * (
                    segment['TotDist'].iloc[index] - length)
            target_y = last_y - (last_y - first_y) / segment['dist'].iloc[index] * (
                    segment['TotDist'].iloc[index] - length)
            delta_x = (target_x - x_origin_value) / self.plume_cell_size
            delta_y = (target_y - y_origin_value) / self.plume_cell_size
            target_center_pts.append([center_pts[0, 0] + delta_x, center_pts[0, 1] + delta_y])
            if len(center_pts) - len(body_pts) == 1 and i == len(center_pts) - 1:
                pass
            else:
                distance = (body_pts[i][1] - body_pts[i][2]) * self.plume_cell_size / 2
                point_right, point_left = find_perpendicular_point(first_x, first_y, last_x, last_y, distance,
                                                                   target_x, target_y)
                delta_x_right = (point_right[0] - target_x) / self.plume_cell_size
                delta_y_right = (point_right[1] - target_y) / self.plume_cell_size
                target_body_right_pts.append([center_pts[0, 0] + delta_x + delta_x_right,
                                              center_pts[0, 1] + delta_y + delta_y_right])
                delta_x_left = (point_left[0] - target_x) / self.plume_cell_size
                delta_y_left = (point_left[1] - target_y) / self.plume_cell_size
                target_body_left_pts.append([center_pts[0, 0] + delta_x + delta_x_left,
                                             center_pts[0, 1] + delta_y + delta_y_left])

        target_center_pts = np.array(target_center_pts)
        target_body_right_pts = np.array(target_body_right_pts)
        target_body_left_pts = np.array(target_body_left_pts)
        target_body_pts = np.vstack((target_body_left_pts, target_body_right_pts))
        return target_center_pts, target_body_pts

    def get_target_points_gis(self, segment, center_pts, body_pts, xvalue, yvalue):
        """
        Get the target points for warping
        """
        segment['dist'] = segment['TotDist'] - segment['TotDist'].shift(1)
        segment.loc[0, 'dist'] = segment['TotDist'].iloc[0]

        target_center_pts = []
        origin_center_pts = []
        target_body_pts_left = []
        target_body_pts_right = []
        origin_body_pts_left = []
        origin_body_pts_right = []

        for i in range(len(center_pts)):
            center_origin_x = xvalue + center_pts[i] * self.plume_cell_size
            center_origin_y = yvalue
            length = (center_pts[i] - center_pts[0]) * self.plume_cell_size
            index = (segment['TotDist'] >= length).idxmax()
            if (i == len(center_pts) - 1 and index == 0) or length >= segment['TotDist'].iloc[-1]:
                index = len(segment) - 1
            first_x = segment['Shape'].iloc[index].firstPoint.X
            first_y = segment['Shape'].iloc[index].firstPoint.Y
            last_x = segment['Shape'].iloc[index].lastPoint.X
            last_y = segment['Shape'].iloc[index].lastPoint.Y
            target_x = last_x - (last_x - first_x) / segment['dist'].iloc[index] * (
                    segment['TotDist'].iloc[index] - length)
            target_y = last_y - (last_y - first_y) / segment['dist'].iloc[index] * (
                    segment['TotDist'].iloc[index] - length)
            origin_center_pts.append([center_origin_x, center_origin_y])
            target_center_pts.append([target_x, target_y])

            if len(center_pts) - len(body_pts) != 1 or i != len(center_pts) - 1:
                body_origin_x = center_origin_x
                distance = (body_pts[i][1] - body_pts[i][0]) * self.plume_cell_size / 2
                point_right, point_left = find_perpendicular_point(first_x, first_y, last_x, last_y, distance,
                                                                   target_x, target_y)
                origin_body_pts_right.append([body_origin_x, center_origin_y - distance])
                origin_body_pts_left.append([body_origin_x, center_origin_y + distance])
                target_body_pts_right.append(point_right)
                target_body_pts_left.append(point_left)
        target_body_pts = np.vstack((target_body_pts_left[::-1], target_body_pts_right))
        origin_body_pts = np.vstack((origin_body_pts_left[::-1], origin_body_pts_right))
        return np.array(target_center_pts), np.array(origin_center_pts), target_body_pts, origin_body_pts

    def modify_warped_array(self, array, target_pts, plume_array, max_value):
        """
        Modify the warped array
        """
        p1 = target_pts[0: 6, :]
        p2 = target_pts[int(target_pts.shape[0] / 2): int(target_pts.shape[0] / 2) + 6, :]
        for i in range(6):
            if i == 0:
                line_a = p2[i, 1] - p1[i, 1]
                line_b = p1[i, 0] - p2[i, 0]
                line_c = p2[i, 0] * p1[i, 1] - p1[i, 0] * p2[i, 1]
                x, y = np.meshgrid(np.arange(array.shape[1]), np.arange(array.shape[0]))
                values = line_a * x + line_b * y + line_c
                array[values > 0] = np.nan
            else:
                line_a1 = p1[i - 1, 1] - p1[i, 1]
                line_b1 = p1[i, 0] - p1[i - 1, 0]
                line_c1 = p1[i - 1, 0] * p1[i, 1] - p1[i, 0] * p1[i - 1, 1]
                x1, y1 = np.meshgrid(np.arange(array.shape[1]), np.arange(array.shape[0]))
                values1 = line_a1 * x1 + line_b1 * y1 + line_c1
                array[values1 > 0] = np.nan

                line_a2 = p2[i, 1] - p2[i - 1, 1]
                line_b2 = p2[i - 1, 0] - p2[i, 0]
                line_c2 = p2[i, 0] * p2[i - 1, 1] - p2[i - 1, 0] * p2[i, 1]
                x2, y2 = np.meshgrid(np.arange(array.shape[1]), np.arange(array.shape[0]))
                values2 = line_a2 * x2 + line_b2 * y2 + line_c2
                array[values2 > 0] = np.nan
        if plume_array[:, -1].max() > self.threshold:
            p2 = target_pts[int(target_pts.shape[0] / 2) - 1, :]
            p1 = target_pts[-1, :]
            line_a = p2[1] - p1[1]
            line_b = p1[0] - p2[0]
            line_c = p2[0] * p1[1] - p1[0] * p2[1]
            x, y = np.meshgrid(np.arange(array.shape[1]), np.arange(array.shape[0]))
            values = line_a * x + line_b * y + line_c
            array[values > 0] = np.nan
        array[array < self.threshold] = np.nan
        array[array > max_value] = max_value
        return array

    @staticmethod
    def is_file_path(input_string):
        return os.path.sep in input_string


def create_shapefile(save_path, name, crs):
    arcpy.CreateFeatureclass_management(
        out_path=save_path,
        out_name=name,
        geometry_type="POINT",
        spatial_reference=crs)

    arcpy.AddField_management(name, "PathID", "LONG")
    arcpy.AddField_management(name, "is2D", "LONG")
    arcpy.AddField_management(name, "domBdy", "LONG")
    arcpy.AddField_management(name, "decayCoeff", "DOUBLE")
    arcpy.AddField_management(name, "avgVel", "DOUBLE")
    arcpy.AddField_management(name, "avgPrsity", "DOUBLE")
    arcpy.AddField_management(name, "DispL", "DOUBLE")
    arcpy.AddField_management(name, "DispTH", "DOUBLE")
    arcpy.AddField_management(name, "DispTV", "DOUBLE")
    arcpy.AddField_management(name, "SourceY", "DOUBLE")
    arcpy.AddField_management(name, "SourceZ", "DOUBLE")
    arcpy.AddField_management(name, "MeshDX", "DOUBLE")
    arcpy.AddField_management(name, "MeshDY", "DOUBLE")
    arcpy.AddField_management(name, "MeshDZ", "DOUBLE")
    arcpy.AddField_management(name, "plumeTime", "DOUBLE")
    arcpy.AddField_management(name, "pathTime", "DOUBLE")
    arcpy.AddField_management(name, "plumeLen", "DOUBLE")
    arcpy.AddField_management(name, "pathLen", "DOUBLE")
    arcpy.AddField_management(name, "plumeArea", "DOUBLE")
    arcpy.AddField_management(name, "mslnRtNmr", "DOUBLE")
    arcpy.AddField_management(name, "massInRate", "DOUBLE")
    arcpy.AddField_management(name, "massDNRate", "DOUBLE")
    arcpy.AddField_management(name, "srcAngle", "DOUBLE")
    arcpy.AddField_management(name, "warp", "LONG")
    arcpy.AddField_management(name, "PostP", "LONG")
    arcpy.AddField_management(name, "Init_conc", "DOUBLE")
    arcpy.AddField_management(name, "volFac", "DOUBLE")
    arcpy.AddField_management(name, "nextConc", "DOUBLE")
    arcpy.AddField_management(name, "threshConc", "DOUBLE")
    arcpy.AddField_management(name, "WBId_plume", "LONG")
    arcpy.AddField_management(name, "WBId_path", "LONG")


def find_perpendicular_point(x1, y1, x2, y2, distance, x0, y0):
    dx = x2 - x1
    dy = y2 - y1

    direction_vector = np.array([dx, dy]) / math.sqrt(dx ** 2 + dy ** 2)
    perpendicular_vector_left = np.array([-dy, dx]) / math.sqrt(dx ** 2 + dy ** 2)
    perpendicular_vector_right = np.array([dy, -dx]) / math.sqrt(dx ** 2 + dy ** 2)

    point_right = np.array([x0, y0]) + perpendicular_vector_right * distance
    point_left = np.array([x0, y0]) + perpendicular_vector_left * distance

    return point_right, point_left


# ======================================================================
# Main program for debugging
if __name__ == '__main__':
    arcpy.env.workspace = ".\\test_pro"
    whethernh4 = True
    source_location = os.path.join(arcpy.env.workspace, "OneSepticTank.shp")
    water_bodies = os.path.join(arcpy.env.workspace, "waterbodies")
    particlepath = os.path.join(arcpy.env.workspace, "demopath.shp")

    no3output = os.path.join(arcpy.env.workspace, "demo1no3")
    nh4output = os.path.join(arcpy.env.workspace, "demo1nh4")

    option0 = "DomenicoRobbinsSSDecay2D"
    option1 = 48
    option2 = "Polyorder2"
    option3 = 0.000001
    option4 = "medium"
    option5 = "Specified z"  # input mass rate or z

    param1 = 20000
    param2 = 6
    param3 = 1
    param4 = False
    param5 = 3.0
    param6 = 0.4

    no3param0 = 40
    no3param1 = 2.113
    no3param2 = 0.234
    no3param3 = 0.008
    no3param4 = 1000.0
    nh4param0 = 5
    nh4param1 = 2.113
    nh4param2 = 0.234
    nh4param3 = 0.0008
    nh4param4 = 1.42
    nh4param5 = 4

    arcpy.AddMessage("starting geoprocessing")
    start_time = datetime.datetime.now()
    Tr = Transport(whethernh4, source_location, water_bodies, particlepath, no3output, nh4output,
                   option0, option1, option2, option3, option4, option5,
                   param1, param2, param3, param4, param5, param6,
                   no3param0, no3param1, no3param2, no3param3, no3param4,
                   nh4param0, nh4param1, nh4param2, nh4param3, nh4param4, nh4param5)
    # cProfile.run('Tr.calculate_plumes()', 'transport.bin')
    # profile_stats = pstats.Stats('transport.bin')
    # with open('transport.txt', 'w') as output_file:
    #     profile_stats.strip_dirs().sort_stats('cumulative').print_stats(output_file)

    Tr.calculate_plumes()
    end_time = datetime.datetime.now()
    print("Total time: {}".format(end_time - start_time))
    print("Tests successful!")