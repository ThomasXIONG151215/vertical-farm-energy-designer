"""BJAAF Exp_c regression gate: engine skeleton reproduces Stage 1.

Skipped when the dataset file is absent (data/datasets is not shipped).
"""
import os

import numpy as np
import pandas as pd
import pytest

from vfed.calibration import (ClimateSeries, GrowthObservations,
                              fit_c_rad_phot, anchor_c_pl_d)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
XLSX = os.path.join(REPO, "data", "datasets", "bjaaf-lettuce-growth",
                    "Greenhouse Climate & Crop data_Exp_c.xlsx")

pytestmark = pytest.mark.skipif(not os.path.exists(XLSX),
                                reason="BJAAF Exp_c dataset not present")


def test_engine_skeleton_reproduces_stage1():
    clim = pd.read_excel(XLSX, sheet_name="Greenhouse climate")
    clim.columns = ["time", "co2", "temp", "rh", "rad"]
    gro = pd.read_excel(XLSX, sheet_name="Lettuce growth summary")
    gro = gro[["Time", "Xd [kg m-2]", "LAI [-]"]].rename(
        columns={"Time": "date", "Xd [kg m-2]": "xd", "LAI [-]": "lai"})

    obs = GrowthObservations(times=gro["date"], x_d=gro["xd"].to_numpy(),
                             lai=gro["lai"].to_numpy())
    anchor = anchor_c_pl_d(obs)
    assert abs(anchor.value - 32.7) <= 0.1          # Stage 1 LSQ value
    assert abs(anchor.c_regression - 35.1) <= 0.1   # Stage 1 cross-check

    climate = ClimateSeries(times=clim["time"], temp_c=clim["temp"].to_numpy(),
                            co2_ppm=clim["co2"].to_numpy(),
                            par_w=0.5 * clim["rad"].to_numpy(), dt_s=300.0)
    gro_w = gro[gro["date"] > clim["time"].iloc[0]].reset_index(drop=True)
    xd0 = float(gro["xd"].iloc[1])
    obs_xd = gro_w["xd"].to_numpy()
    idx = np.searchsorted(clim["time"].to_numpy(),
                          pd.DatetimeIndex(gro_w["date"]).to_numpy())
    assert len(idx) == 10

    c_rp, rmse, _ = fit_c_rad_phot(climate, xd0, anchor.value, idx, obs_xd)
    assert abs(c_rp / 5.17e-9 - 1.0) <= 0.01        # Stage 1 fit value
    assert abs(rmse / 0.0074 - 1.0) <= 0.02         # Stage 1 RMSE
