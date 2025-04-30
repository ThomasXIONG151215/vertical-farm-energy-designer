idea is to use real existing pv panels and liion battery energy storage system to model the pvbes system.

## PV
G:\PVBES_Design\writings\pv_equip_reference.jpg

G:\PVBES_Design\notes\2024-05-18_PV_Single_Diode_Model_Full.md

## Battery

G:\PVBES_Design\notes\2024-05-17_Battery_Flow_Calculation_Model_Full.md

G:\PVBES_Design\writings\bess_equip_reference.jpg

## PVBES mechanism example

One special thing to emphasize is that PFAL can adjust its photoperiod to start at any time of the day since it is based on artifical LED lighting instead of natural sunlight to grow crops.

showcase how it is done; 上海，2024年

光伏(30m2)
vs
光伏+储能(10kWh)

光周期4点开始
vs
20点开始

G:\PVBES_Design\test_case\shanghai\results\mechanism_plots\mechanism_analysis\mechanism_daily_profile.png
G:\PVBES_Design\test_case\shanghai\results\mechanism_plots\mechanism_analysis\mechanism_metrics.png
G:\PVBES_Design\test_case\shanghai\results\mechanism_plots\mechanism_analysis\mechanism_plot_C.png
G:\PVBES_Design\test_case\shanghai\results\mechanism_plots\mechanism_analysis\mechanism_plot_D.png
G:\PVBES_Design\test_case\shanghai\results\mechanism_plots\mechanism_analysis\mechanism_plot_E.png
G:\PVBES_Design\test_case\shanghai\results\mechanism_plots\mechanism_analysis\mechanism_plot_F.png

fig3. A is the mechanism daily profile selected,

B is the metrics of the mechanism directly comparing pv utilization and grid dependency (load coverage), mechanism plot C is for 4am pv-only, we can observe that pv generation much higher than load profile to cover loads during the day, but pv is not generated as there is no sun at night, and the sytem has to import from the grid. D showcase when we have battery, during the day the battery is quickly charged up to 10 kwh and then the remaining pv output is either used to full fill or wasted, and at night since the battery is not big enoug, it cannot cover the entire night load, so before sun is up gotta import from the grid. E and F are for 8pm, meaning half of the photoperiod inside the PFAL correspond to no sun time exterior to the PFAL. Which explains why the pv utilization is lower at 8pm combined to if photoperiod starts at 4.
So we could observe that pv and battery are both important and their combination with customizable photoperiod start hour represent a great search space for optimization in the pvbes system integrated with PFAL.
