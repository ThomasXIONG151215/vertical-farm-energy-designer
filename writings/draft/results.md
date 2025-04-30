We selected representative cities from different climate zones to showcase the potential of implementing the pvbes system integrated with PFAL.


## Results/Findings

- FigS1 shows the validation of both energyplus model and pv energy output modeling.  G:\PVBES_Design\results\validate_ep   G:\PVBES_Design\results\validate_pv
    - S1A shows the validation of energyplus model hvac energy forecast capability during the period of 2023 August (R2, cvrmse, nmse)
    - S1B shows the trend of hvac energy inside the pfal according to the energyplus model when both the envelope conductivity and thickness differ; it is clear that the more the envelope conductivity is high the more the pfal is sensible to exterior climate thus the need for HVAC is higher, and for thickness it is the opposite.
    - S1C showcase the validation of PV power generation model in comparison to the parameters from open accessible Jinko Solar product datasheet.
    - S1D showcase the variation trend of pv power generation in relation to solar irradiance and outdoor temperature. Conform to the models equations the pv output tend to decrease while the temperature rises, conform to the physical basis behind pv modules.




- selected representative cities for each climate zone in China
- generate each of their corresponding load profile, one load profile for one photoperiod start hour by assuming that when set one photoperiod start, it will stay the same for the whole year. One photoperiod start hour correspond load profile will next be called schedule solution.
- first analyze the climate, G:\PVBES_Design\results\city_climate_energy
    - fig5.A compare their average daily radiation accumulation;shanghai at the middle, laza and urumqi at the most
    - fig5.B compare the temperature; harbin and laza as the lowest
    - fig5.C The other energy sources other than HVAC are all the same whether the city or the start hour, only HVAC is the most sensible to both climate and potentially to the start of photoperiod. So in fig5C we compare the daily hvac energy consumption average value of all schedule solution of each city, the error line shows the standard deviation. The low deviation for each city demonstrates that on whole year basis hvac energy consumption does not differ much according to the start hour of photoperiod.  However the mean value itself is lower in cold climates and higher in cities with high average mean temperature. It could be explained by the fact that inside a PFAL there are heats from equipment, thus in cold seasons there is less need for the HVAC to do heating however in summer the heats from equipment along with the thermal infiltration from outdoor adds up pushes the PFAL HVAC unit to do more work thus consuming more energies. THis trend demonstrate similar pattern to fig 1B.
    - fig5. shows the over year average tempearture in z axis for four distinct time periods, 0-6,6-12,12-18 and 18-24.  And in color the average radiation intensity



- second we analyze the workflow results. G:\PVBES_Design\results\city_results
    - fig6A showcase the optimal lcoe we could obtain for a payback period for respectively around 1 year and around 3 years distinctly【distinct two bars】
    - fig6B shows the corresponding pv and battery size combination for each city when optimizing lcoe
    - fig6C shows the optimal payback period if we set specific target lcoe, we respectivley set 0.05$ and 0.08$
    - fig6D shows the sizing parameters corresponding to fig6C
    - fig6E shows the minimum cost for each city to achieve a tlps<1%, which would indicate that the grid dependency is so low that the PFAL might not actually need any grid import and cna run as microgrid.
    - fig6F shows a correlation map showing the correlation between LCOE, payback period and TLPS with climate radiation, temperature and photoperiod start hour.

